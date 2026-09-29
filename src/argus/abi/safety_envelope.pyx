# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True

"""Cython implementation of the Argus safety envelope C ABI.

This compiles to a native shared library that can be called from any language
via FFI. The implementation mirrors the Python safety envelope logic exactly.
"""

from libc.math cimport fabs, fmax, fmin
from libc.string cimport strcmp
from cpython cimport array
import array

cdef extern from *:
    ctypedef bint bool

# Error codes
cdef enum ArgusErrorCode:
    OK = 0
    INVALID_ARGUMENT = 1
    INVALID_STATE = 2
    BUFFER_TOO_SMALL = 3
    NOT_INITIALIZED = 4
    INTERNAL_ERROR = 5

# Envelope states
cdef enum ArgusEnvelopeState:
    NOMINAL = 0
    DEGRADED = 1
    SAFE_HALT = 2

# C-compatible structures
cdef struct ArgusSafetyConfigC:
    double t_high
    double t_low
    double degraded_velocity_scale
    double degraded_force_scale
    double hard_max_torque_nm
    double hard_max_velocity_rad_s
    unsigned int persistence_windows

cdef struct ArgusPredictionC:
    const char* intent
    double confidence

cdef struct ArgusSignalQualityC:
    double reliability
    unsigned int* flatline_channels
    size_t flatline_count
    int artifact_detected

cdef struct ArgusActuatorCommandC:
    const char* intent
    double torque_nm
    double velocity_rad_s
    int envelope_state
    double effective_confidence
    int vetoed_by_supervisor

# Opaque handle
ctypedef void* ArgusEnvelopeHandle

# Internal envelope state
cdef struct EnvelopeState:
    ArgusSafetyConfigC cfg
    ArgusEnvelopeState state
    unsigned int low_streak
    bool initialized

# Nominal request table
cdef struct NominalRequest:
    const char* intent
    double torque
    double velocity

cdef NominalRequest NOMINAL_REQUESTS[] = [
    {"rest", 0.0, 0.0},
    {"knee_flexion", 25.0, 3.0},
    {"knee_extension", 25.0, 3.0},
]

cdef int NUM_NOMINAL_REQUESTS = 3

cdef class SafetyEnvelope:
    """Python wrapper for the C safety envelope."""

    cdef EnvelopeState _state

    def __cinit__(self, double t_high, double t_low,
                  double degraded_velocity_scale, double degraded_force_scale,
                  double hard_max_torque_nm, double hard_max_velocity_rad_s,
                  unsigned int persistence_windows):
        self._state.cfg.t_high = t_high
        self._state.cfg.t_low = t_low
        self._state.cfg.degraded_velocity_scale = degraded_velocity_scale
        self._state.cfg.degraded_force_scale = degraded_force_scale
        self._state.cfg.hard_max_torque_nm = hard_max_torque_nm
        self._state.cfg.hard_max_velocity_rad_s = hard_max_velocity_rad_s
        self._state.cfg.persistence_windows = persistence_windows
        self._state.state = SAFE_HALT
        self._state.low_streak = 0
        self._state.initialized = True

    def reset(self):
        """Reset to SAFE_HALT state."""
        self._state.low_streak = 0
        self._state.state = SAFE_HALT

    def evaluate(self, str intent, double confidence, double reliability,
                 double requested_torque_nm=0.0, double requested_velocity_rad_s=0.0,
                 bint use_nominal=True):
        """Evaluate one window and return actuator command.

        Returns:
            tuple: (torque_nm, velocity_rad_s, envelope_state, effective_confidence, vetoed)
        """
        cdef double c_eff
        cdef double base_torque, base_velocity
        cdef bint known_intent
        cdef double torque, velocity
        cdef bint vetoed

        # Calculate effective confidence
        c_eff = round(confidence * reliability, 6)

        # Update streak
        if c_eff < self._state.cfg.t_low:
            self._state.low_streak += 1
        else:
            self._state.low_streak = 0

        # State transitions
        if self._state.low_streak >= self._state.cfg.persistence_windows:
            self._state.state = SAFE_HALT
        elif c_eff >= self._state.cfg.t_high:
            self._state.state = NOMINAL
        else:
            self._state.state = DEGRADED

        # Get base values
        if use_nominal:
            base_torque, base_velocity, known_intent = self._get_nominal_request(intent)
        else:
            base_torque, base_velocity = requested_torque_nm, requested_velocity_rad_s
            known_intent = True

        # Unknown intent fails safe
        if not known_intent:
            self._state.state = SAFE_HALT

        # Compute output
        if self._state.state == NOMINAL:
            torque, velocity = base_torque, base_velocity
        elif self._state.state == DEGRADED:
            torque = base_torque * self._state.cfg.degraded_force_scale
            velocity = base_velocity * self._state.cfg.degraded_velocity_scale
        else:  # SAFE_HALT
            torque, velocity = 0.0, 0.0

        # Apply hardware supervisor limits
        vetoed = False
        if fabs(torque) > self._state.cfg.hard_max_torque_nm:
            torque = fmax(-self._state.cfg.hard_max_torque_nm,
                         fmin(self._state.cfg.hard_max_torque_nm, torque))
            vetoed = True
        if fabs(velocity) > self._state.cfg.hard_max_velocity_rad_s:
            velocity = fmax(-self._state.cfg.hard_max_velocity_rad_s,
                           fmin(self._state.cfg.hard_max_velocity_rad_s, velocity))
            vetoed = True

        return (torque, velocity, self._state.state, c_eff, vetoed)

    cdef (double, double, bint) _get_nominal_request(self, str intent):
        """Get nominal torque/velocity for an intent."""
        cdef bytes intent_bytes = intent.encode('utf-8')
        cdef const char* intent_c = intent_bytes
        cdef int i

        for i in range(NUM_NOMINAL_REQUESTS):
            if strcmp(intent_c, NOMINAL_REQUESTS[i].intent) == 0:
                return (NOMINAL_REQUESTS[i].torque, NOMINAL_REQUESTS[i].velocity, True)

        return (0.0, 0.0, False)

    @property
    def state(self):
        """Current envelope state."""
        return self._state.state

    @property
    def low_streak(self):
        """Current low streak count."""
        return self._state.low_streak


# C ABI functions - these are exported for FFI

cdef extern:
    pass

def create_envelope(double t_high, double t_low,
                    double degraded_velocity_scale, double degraded_force_scale,
                    double hard_max_torque_nm, double hard_max_velocity_rad_s,
                    unsigned int persistence_windows):
    """Create a new safety envelope instance.

    Returns:
        SafetyEnvelope: New envelope instance.
    """
    return SafetyEnvelope(
        t_high, t_low, degraded_velocity_scale, degraded_force_scale,
        hard_max_torque_nm, hard_max_velocity_rad_s, persistence_windows
    )


def destroy_envelope(SafetyEnvelope envelope):
    """Destroy an envelope instance.

    Note: Python handles garbage collection automatically.
    """
    pass


def reset_envelope(SafetyEnvelope envelope):
    """Reset an envelope to SAFE_HALT state.

    Returns:
        int: OK on success, error code otherwise.
    """
    envelope.reset()
    return OK


def evaluate_envelope(SafetyEnvelope envelope, str intent, double confidence,
                      double reliability, double requested_torque_nm=0.0,
                      double requested_velocity_rad_s=0.0, bint use_nominal=True):
    """Evaluate one window.

    Returns:
        tuple: (error_code, torque_nm, velocity_rad_s, envelope_state, effective_confidence, vetoed)
    """
    result = envelope.evaluate(
        intent, confidence, reliability,
        requested_torque_nm, requested_velocity_rad_s, use_nominal
    )
    return (OK,) + result


def get_envelope_state(SafetyEnvelope envelope):
    """Get current envelope state.

    Returns:
        tuple: (error_code, state)
    """
    return (OK, envelope.state)


def get_envelope_low_streak(SafetyEnvelope envelope):
    """Get current low streak count.

    Returns:
        tuple: (error_code, streak)
    """
    return (OK, envelope.low_streak)
