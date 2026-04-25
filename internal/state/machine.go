// Package state implements the system state machine (§3.3).
//
// This is a placeholder for the Go migration.  The Python implementation
// lives in algotrader/orchestrator/state_machine.py.
package state

import "fmt"

type State string

const (
	Disabled          State = "DISABLED"
	Starting          State = "STARTING"
	Idle              State = "IDLE"
	Ingesting         State = "INGESTING"
	Processing        State = "PROCESSING"
	PendingApproval   State = "PENDING_APPROVAL"
	Executing         State = "EXECUTING"
	Monitoring        State = "MONITORING"
	Reconciling       State = "RECONCILING"
	Halt              State = "HALT"
)

type Machine struct {
	state State
}

func New() *Machine {
	return &Machine{state: Disabled}
}

func (m *Machine) State() State {
	return m.state
}

func (m *Machine) ForceHalt() {
	m.state = Halt
}

func (m *Machine) Resume() {
	if m.state == Halt {
		m.state = Idle
	}
}
