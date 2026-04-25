"""
State machine for the AlgoTrader orchestrator.

Wraps the SystemState enum with validated transition logic.  All state
changes are funnelled through a single method so that the rest of S1 never
writes the state attribute directly — this is the only file that understands
which transitions are legal.

Allowed transitions (mirrors §3.3):
    DISABLED   → STARTING
    STARTING   → IDLE | HALT
    IDLE       → INGESTING | PROCESSING | PENDING_APPROVAL | EXECUTING
                 | MONITORING | RECONCILING | HALT
    INGESTING  → IDLE | HALT
    PROCESSING → PENDING_APPROVAL | IDLE | HALT
    PENDING_APPROVAL → APPROVED | PARTIALLY_APPROVED | IDLE | HALT
    APPROVED   → EXECUTING | HALT
    PARTIALLY_APPROVED → EXECUTING | HALT
    EXECUTING  → MONITORING | IDLE | HALT
    MONITORING → RECONCILING | IDLE | HALT
    RECONCILING → IDLE | HALT
    HALT       → IDLE   (manual RESUME only)
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from shared.constants import SystemState
from shared.exceptions import ConfigError
from shared.logger import get_logger

if TYPE_CHECKING:
    pass

log = get_logger(__name__)

# Map each state to the set of states it may transition into.
_VALID_TRANSITIONS: dict[SystemState, frozenset[SystemState]] = {
    SystemState.DISABLED: frozenset({SystemState.STARTING}),
    SystemState.STARTING: frozenset({SystemState.IDLE, SystemState.HALT}),
    SystemState.IDLE: frozenset({
        SystemState.INGESTING,
        SystemState.PROCESSING,
        SystemState.PENDING_APPROVAL,
        SystemState.EXECUTING,
        SystemState.MONITORING,
        SystemState.RECONCILING,
        SystemState.HALT,
    }),
    SystemState.INGESTING: frozenset({SystemState.IDLE, SystemState.HALT}),
    SystemState.PROCESSING: frozenset({
        SystemState.PENDING_APPROVAL,
        SystemState.IDLE,
        SystemState.HALT,
    }),
    SystemState.PENDING_APPROVAL: frozenset({
        SystemState.APPROVED,
        SystemState.PARTIALLY_APPROVED,
        SystemState.IDLE,
        SystemState.HALT,
    }),
    SystemState.APPROVED: frozenset({SystemState.EXECUTING, SystemState.HALT}),
    SystemState.PARTIALLY_APPROVED: frozenset({SystemState.EXECUTING, SystemState.HALT}),
    SystemState.EXECUTING: frozenset({SystemState.MONITORING, SystemState.IDLE, SystemState.HALT}),
    SystemState.MONITORING: frozenset({SystemState.RECONCILING, SystemState.IDLE, SystemState.HALT}),
    SystemState.RECONCILING: frozenset({SystemState.IDLE, SystemState.HALT}),
    # HALT → IDLE is the *only* exit from HALT (manual RESUME).
    SystemState.HALT: frozenset({SystemState.IDLE}),
}


class StateMachine:
    """Thread-safe wrapper around SystemState with validated transitions.

    Parameters
    ----------
    initial:
        The starting state for this run.  Ordinarily ``SystemState.DISABLED``
        until ``startup()`` advances it to ``STARTING``.
    """

    def __init__(self, initial: SystemState = SystemState.DISABLED) -> None:
        self._state: SystemState = initial
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def state(self) -> SystemState:
        """Current system state (read-only outside this class)."""
        with self._lock:
            return self._state

    def transition(self, target: SystemState, *, reason: str = "") -> None:
        """Attempt a state transition.

        Parameters
        ----------
        target:
            The desired next state.
        reason:
            Human-readable explanation logged at INFO level.

        Raises
        ------
        ConfigError
            If the transition is not permitted from the current state.  We
            reuse ConfigError because an illegal transition always indicates
            a programming error or an unexpected external event — both
            warrant a loud, typed exception that S1 can catch and escalate.
        """
        with self._lock:
            current = self._state
            allowed = _VALID_TRANSITIONS.get(current, frozenset())
            if target not in allowed:
                raise ConfigError(
                    f"Illegal state transition: {current.value} → {target.value}. "
                    f"Reason: {reason or 'unspecified'}"
                )
            self._state = target
            log.info(
                "state_transition",
                previous=current.value,
                current=target.value,
                reason=reason,
            )

    def force_halt(self, reason: str) -> None:
        """Unconditionally set state to HALT from any state.

        This is the only method that bypasses the transition table.  It must
        only be called by the watchdog or the top-level exception handler after
        a CRITICAL event — never as part of normal flow.
        """
        with self._lock:
            previous = self._state
            self._state = SystemState.HALT
        log.warning(
            "state_force_halt",
            previous=previous.value,
            reason=reason,
        )

    def is_halted(self) -> bool:
        """Return True when the system is in HALT state."""
        return self.state == SystemState.HALT

    def is_operational(self) -> bool:
        """Return True when the system is able to run jobs (not DISABLED, not HALT)."""
        s = self.state
        return s not in (SystemState.DISABLED, SystemState.HALT, SystemState.STARTING)
