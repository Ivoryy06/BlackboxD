








package main

import (
	"database/sql"
	"fmt"
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
var dbPath string

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
	// modernc ignores some DSN options, so set the important ones explicitly.
	conn.Exec("PRAGMA journal_mode = WAL;")
	conn.Exec("PRAGMA busy_timeout = 5000;")
	return conn
}

// checkSchema makes a missing database a readable error instead of a
// mysterious 500 from every endpoint.
func checkSchema() error {
	var name string
	err := db.QueryRow("SELECT name FROM sqlite_master WHERE type='table' AND name='events'").Scan(&name)
	if err != nil {
		return fmt.Errorf("events table not found in %s — start the blackboxd daemon once so it can create it", dbPath)
	}
	return nil
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
	if err := db.QueryRow("SELECT COUNT(*) FROM events").Scan(&count); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	if err := db.QueryRow("SELECT MIN(timestamp), MAX(timestamp) FROM events").Scan(&minTs, &maxTs); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"total_events": count,
		"earliest":     minTs,
		"latest":       maxTs,
	})
}

func health(c *gin.Context) {
	if err := checkSchema(); err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"status": "no schema", "db": dbPath, "error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "ok", "db": dbPath})
}

func main() {
	dbPath = os.Getenv("BLACKBOXD_DB")
	if dbPath == "" {
		home, _ := os.UserHomeDir()
		dbPath = home + "/.local/share/blackboxd/events.db"
	}
	port := os.Getenv("BLACKBOXD_PORT")
	if port == "" {
		port = "8080"
	}

	db = openDB(dbPath)
	defer db.Close()

	if err := checkSchema(); err != nil {
		log.Printf("warning: %v", err)
	}

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
		c.JSON(http.StatusOK, gin.H{"ok": true, "ts": time.Now().Unix()})
	})
	r.GET("/api/health", health)

	log.Printf("blackboxd-api listening on :%s (db: %s)", port, dbPath)
	r.Run(":" + port)
}
