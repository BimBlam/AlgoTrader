// Package models defines cross-language data contracts.
//
// These structs mirror the PostgreSQL schema (§4.2) and are used by
// both Go and Python processes.  JSON tags ensure consistent serialization.
package models

import (
	"time"
)

// Job mirrors the jobs table.
type Job struct {
	ID           int       `json:"id"`
	RunID        string    `json:"run_id"`
	JobType      string    `json:"job_type"`
	Status       string    `json:"status"`
	CreatedAt    time.Time `json:"created_at"`
	StartedAt    *time.Time `json:"started_at,omitempty"`
	CompletedAt  *time.Time `json:"completed_at,omitempty"`
	WorkerPID    *int      `json:"worker_pid,omitempty"`
	ErrorMsg     *string   `json:"error_msg,omitempty"`
	RetryCount   int       `json:"retry_count"`
	ConfigHash   string    `json:"config_hash"`
}

// Signal mirrors the signals table.
type Signal struct {
	ID            int       `json:"id"`
	RunID         string    `json:"run_id"`
	CreatedAt     time.Time `json:"created_at"`
	Ticker        string    `json:"ticker"`
	Strategy      string    `json:"strategy"`
	Side          string    `json:"side"`
	RawScore      float64   `json:"raw_score"`
	SentimentAdj  float64   `json:"sentiment_adj"`
	Regime        string    `json:"regime"`
	TargetSizeUSD float64   `json:"target_size_usd"`
	Status        string    `json:"status"`
	ApprovedBy    *string   `json:"approved_by,omitempty"`
	ApprovedAt    *time.Time `json:"approved_at,omitempty"`
	Notes         *string   `json:"notes,omitempty"`
}

// Order mirrors the orders table.
type Order struct {
	ID          int       `json:"id"`
	SignalID    int       `json:"signal_id"`
	Ticker      string    `json:"ticker"`
	Side        string    `json:"side"`
	OrderType   string    `json:"order_type"`
	Quantity    int       `json:"quantity"`
	LimitPrice  float64   `json:"limit_price"`
	Status      string    `json:"status"`
	AccountType string    `json:"account_type"`
	FilledQty   int       `json:"filled_qty"`
	AvgPrice    float64   `json:"avg_price"`
	CreatedAt   time.Time `json:"created_at"`
	UpdatedAt   time.Time `json:"updated_at"`
}
