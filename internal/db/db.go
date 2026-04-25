// Package db provides PostgreSQL connectivity for the Go side.
//
// This is a placeholder for the Go migration.  The Python implementation
// lives in algotrader/shared/db.py (SQLAlchemy 2.0).
package db

import (
	"context"
	"fmt"
)

// Pool wraps a pgx connection pool (not yet wired).
type Pool struct {
	DSN string
}

func New(dsn string) *Pool {
	return &Pool{DSN: dsn}
}

func (p *Pool) Ping(ctx context.Context) error {
	fmt.Println("db: ping (placeholder)")
	return nil
}
