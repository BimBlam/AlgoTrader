// cmd/algotrade/main.go
//
// Future unified entry point for the Go side of AlgoTrader.
//
// Migration plan:
//   1. Implement internal/scheduler (cron + job queue polling)
//   2. Implement internal/state (system state machine)
//   3. Implement internal/ibkr (TWS API client)
//   4. Run Go orchestrator side-by-side with Python workers
//   5. Gradually retire Python S1 (orchestrator) and S6 (execution)
//
// For now this binary prints a bootstrap message and exits.

package main

import (
	"fmt"
	"os"
)

func main() {
	fmt.Println("AlgoTrader Go bootstrap — not yet implemented.")
	fmt.Println("See MIGRATION.md for the Go migration roadmap.")
	os.Exit(0)
}
