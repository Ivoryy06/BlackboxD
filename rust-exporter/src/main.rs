/// blackboxd-export — high-performance exporter for BlackboxD event data
///
/// Reads from the SQLite store written by the Python daemon and exports
/// to JSON or CSV.
///
/// Usage:
///   blackboxd-export --format json --output activity.json
///   blackboxd-export --format csv  --output activity.csv
///   blackboxd-export --format json --since 1700000000 --until 1700086400

use clap::{Parser, ValueEnum};
use rusqlite::{Connection, OpenFlags};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Parser)]
#[command(name = "blackboxd-export", about = "Export BlackboxD activity data")]
struct Cli {
    /// Output format
    #[arg(short, long, default_value = "json")]
    format: Format,

    /// Output file (default: stdout)
    #[arg(short, long)]
    output: Option<PathBuf>,

    /// Only events after this Unix timestamp
    #[arg(long)]
    since: Option<f64>,

    /// Only events before this Unix timestamp
    #[arg(long)]
    until: Option<f64>,

    /// Path to the SQLite database
    #[arg(long, env = "BLACKBOXD_DB")]
    db: Option<PathBuf>,
}

#[derive(Clone, ValueEnum)]
enum Format {
    Json,
    Csv,
}

#[derive(Debug, Serialize, Deserialize)]
struct Event {
    id: i64,
    kind: String,
    timestamp: f64,
    collector: String,
    app_name: Option<String>,
    app_class: Option<String>,
    window_title: Option<String>,
    workspace: Option<String>,
    idle_seconds: Option<f64>,
}

fn default_db_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/root".into());
    PathBuf::from(home).join(".local/share/blackboxd/events.db")
}

fn load_events(db_path: &PathBuf, since: Option<f64>, until: Option<f64>) -> Vec<Event> {
    let conn = Connection::open_with_flags(db_path, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .expect("Failed to open database");

    let mut clauses: Vec<String> = Vec::new();
    let mut params: Vec<Box<dyn rusqlite::ToSql>> = Vec::new();

    if let Some(s) = since {
        clauses.push("timestamp >= ?".into());
        params.push(Box::new(s));
    }
    if let Some(u) = until {
        clauses.push("timestamp <= ?".into());
        params.push(Box::new(u));
    }

    let where_clause = if clauses.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", clauses.join(" AND "))
    };

    let sql = format!(
        "SELECT id, kind, timestamp, collector, app_name, app_class, \
         window_title, workspace, idle_seconds FROM events {} ORDER BY timestamp ASC",
        where_clause
    );

    let param_refs: Vec<&dyn rusqlite::ToSql> = params.iter().map(|p| p.as_ref()).collect();
    let mut stmt = conn.prepare(&sql).expect("Failed to prepare query");

    stmt.query_map(param_refs.as_slice(), |row| {
        Ok(Event {
            id:           row.get(0)?,
            kind:         row.get(1)?,
            timestamp:    row.get(2)?,
            collector:    row.get(3)?,
            app_name:     row.get(4)?,
            app_class:    row.get(5)?,
            window_title: row.get(6)?,
            workspace:    row.get(7)?,
            idle_seconds: row.get(8)?,
        })
    })
    .expect("Query failed")
    .filter_map(|r| r.ok())
    .collect()
}

fn main() {
    let cli = Cli::parse();
    let db_path = cli.db.unwrap_or_else(default_db_path);

    let events = load_events(&db_path, cli.since, cli.until);

    let output: Box<dyn std::io::Write> = match &cli.output {
        Some(path) => Box::new(std::fs::File::create(path).expect("Cannot create output file")),
        None => Box::new(std::io::stdout()),
    };

    match cli.format {
        Format::Json => {
            serde_json::to_writer_pretty(output, &events).expect("JSON write failed");
        }
        Format::Csv => {
            let mut wtr = csv::Writer::from_writer(output);
            for e in &events {
                wtr.serialize(e).expect("CSV write failed");
            }
            wtr.flush().expect("CSV flush failed");
        }
    }

    eprintln!("Exported {} events.", events.len());
}
