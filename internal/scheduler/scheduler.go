// Package scheduler implements cron-based job scheduling.
//
// This is a placeholder for the Go migration.  The Python implementation
// lives in algotrader/orchestrator/scheduler.py (APScheduler).
package scheduler

import "fmt"

// Scheduler wires cron expressions to job handlers.
type Scheduler struct{}

func New() *Scheduler {
	return &Scheduler{}
}

func (s *Scheduler) Start() error {
	fmt.Println("scheduler: started (placeholder)")
	return nil
}

func (s *Scheduler) Stop() {
	fmt.Println("scheduler: stopped (placeholder)")
}
