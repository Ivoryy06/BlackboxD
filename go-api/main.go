// blackboxd-api — HTTP API server for BlackboxD
// Reads from the SQLite event store written by the Python daemon.
// Endpoints:
//   GET  /api/events          ?since=<unix>&until=<unix>&limit=<n>
//   GET  /api/events/latest   ?n=<count>
//   GET  /api/stats
//   POST /api/refresh         (called by the Lua listener on workspace events)
//   GET  /api/health

package main

import (
	"database/sql"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	_ "modernc.org/sqlite"
)

var db *sql.DB

type Event struct {
	ID          int64    `json:"id"`
	Kind        string   `json:"kind"`
	Timestamp   float64  `json:"timestamp"`
	Collector   string   `json:"collector"`
	AppName     *string  `json:"app_name"`
	AppClass    *string  `json:"app_class"`
	WindowTitle *string  `json:"window_title"`
	Workspace   *string  `json:"workspace"`
	IdleSeconds *float64 `json:"idle_seconds"`
}

func openDB(path string) *sql.DB {
	conn, err := sql.Open("sqlite", path+"?_journal_mode=WAL&_busy_timeout=5000")
	if err != nil {
		log.Fatalf("open db: %v", err)
	}
	conn.SetMaxOpenConns(1)
	return conn
}

func queryEvents(c *gin.Context) {
	var clauses []string
	var args []any

	if s := c.Query("since"); s != "" {
		if v, err := strconv.ParseFloat(s, 64); err == nil {
			clauses = append(clauses, "timestamp >= ?")
			args = append(args, v)
		}
	}
	if u := c.Query("until"); u != "" {
		if v, err := strconv.ParseFloat(u, 64); err == nil {
			clauses = append(clauses, "timestamp <= ?")
			args = append(args, v)
		}
	}

	where := ""
	if len(clauses) > 0 {
		where = "WHERE " + clauses[0]
		for _, cl := range clauses[1:] {
			where += " AND " + cl
		}
	}

	limit := 500
	if l := c.Query("limit"); l != "" {
		if v, err := strconv.Atoi(l); err == nil && v > 0 {
			limit = v
		}
	}

	rows, err := db.Query(
		"SELECT id,kind,timestamp,collector,app_name,app_class,window_title,workspace,idle_seconds FROM events "+where+" ORDER BY timestamp ASC LIMIT ?",
		append(args, limit)...,
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer rows.Close()

	events := make([]Event, 0)
	for rows.Next() {
		var e Event
		if err := rows.Scan(&e.ID, &e.Kind, &e.Timestamp, &e.Collector,
			&e.AppName, &e.AppClass, &e.WindowTitle, &e.Workspace, &e.IdleSeconds); err != nil {
			continue
		}
		events = append(events, e)
	}
	c.JSON(http.StatusOK, events)
}

func latestEvents(c *gin.Context) {
	n := 50
	if v, err := strconv.Atoi(c.Query("n")); err == nil && v > 0 {
		n = v
	}
	rows, err := db.Query(
		"SELECT id,kind,timestamp,collector,app_name,app_class,window_title,workspace,idle_seconds FROM events ORDER BY timestamp DESC LIMIT ?", n,
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer rows.Close()

	events := make([]Event, 0)
	for rows.Next() {
		var e Event
		if err := rows.Scan(&e.ID, &e.Kind, &e.Timestamp, &e.Collector,
			&e.AppName, &e.AppClass, &e.WindowTitle, &e.Workspace, &e.IdleSeconds); err != nil {
			continue
		}
		events = append(events, e)
	}
	c.JSON(http.StatusOK, events)
}

func stats(c *gin.Context) {
	var count int
	var minTs, maxTs *float64
	db.QueryRow("SELECT COUNT(*) FROM events").Scan(&count)
	db.QueryRow("SELECT MIN(timestamp), MAX(timestamp) FROM events").Scan(&minTs, &maxTs)
	c.JSON(http.StatusOK, gin.H{
		"total_events": count,
		"earliest":     minTs,
		"latest":       maxTs,
	})
}

func main() {
	dbPath := os.Getenv("BLACKBOXD_DB")
	if dbPath == "" {
		home, _ := os.UserHomeDir()
		dbPath = home + "/.local/share/blackboxd/events.db"
	}
	port := os.Getenv("BLACKBOXD_PORT")
	if port == "" {
		port = "9099"
	}

	db = openDB(dbPath)
	defer db.Close()

	gin.SetMode(gin.ReleaseMode)
	r := gin.Default()

	r.Use(cors.New(cors.Config{
		AllowOrigins: []string{"*"},
		AllowMethods: []string{"GET", "POST"},
		AllowHeaders: []string{"Content-Type"},
	}))

	r.GET("/api/events", queryEvents)
	r.GET("/api/events/latest", latestEvents)
	r.GET("/api/stats", stats)
	r.POST("/api/refresh", func(c *gin.Context) {
		// Called by the Lua listener on workspace events — just acknowledge.
		c.JSON(http.StatusOK, gin.H{"ok": true, "ts": time.Now().Unix()})
	})
	r.GET("/api/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok", "db": dbPath})
	})

	log.Printf("blackboxd-api listening on :%s (db: %s)", port, dbPath)
	r.Run(":" + port)
}
