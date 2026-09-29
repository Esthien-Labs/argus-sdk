// Argus SDK Rust wrapper
// Safe Rust API over the C ABI

#![allow(non_upper_case_globals)]
#![allow(non_camel_case_types)]
#![allow(non_snake_case)]

include!(concat!(env!("OUT_DIR"), "/bindings.rs"));

use std::ffi::{CStr, CString};
use std::os::raw::c_int;
use std::ptr;

/// Safety envelope operating state
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EnvelopeState {
    Nominal,
    Degraded,
    SafeHalt,
}

impl From<i32> for EnvelopeState {
    fn from(value: i32) -> Self {
        match value {
            0 => EnvelopeState::Nominal,
            1 => EnvelopeState::Degraded,
            2 => EnvelopeState::SafeHalt,
            _ => EnvelopeState::SafeHalt,
        }
    }
}

/// Safety configuration
#[derive(Debug, Clone)]
pub struct SafetyConfig {
    pub t_high: f64,
    pub t_low: f64,
    pub degraded_velocity_scale: f64,
    pub degraded_force_scale: f64,
    pub hard_max_torque_nm: f64,
    pub hard_max_velocity_rad_s: f64,
    pub persistence_windows: u32,
}

impl Default for SafetyConfig {
    fn default() -> Self {
        Self {
            t_high: 0.75,
            t_low: 0.45,
            degraded_velocity_scale: 0.5,
            degraded_force_scale: 0.4,
            hard_max_torque_nm: 40.0,
            hard_max_velocity_rad_s: 6.0,
            persistence_windows: 3,
        }
    }
}

/// Prediction
#[derive(Debug, Clone)]
pub struct Prediction {
    pub intent: String,
    pub confidence: f64,
}

/// Signal quality
#[derive(Debug, Clone)]
pub struct SignalQuality {
    pub reliability: f64,
    pub flatline_channels: Vec<u32>,
    pub artifact_detected: bool,
}

/// Actuator command
#[derive(Debug, Clone)]
pub struct ActuatorCommand {
    pub intent: String,
    pub torque_nm: f64,
    pub velocity_rad_s: f64,
    pub envelope_state: EnvelopeState,
    pub effective_confidence: f64,
    pub vetoed_by_supervisor: bool,
}

/// Safety envelope
pub struct SafetyEnvelope {
    handle: ArgusEnvelopeHandle,
}

impl SafetyEnvelope {
    /// Create a new safety envelope
    pub fn new(config: SafetyConfig) -> Result<Self, c_int> {
        let cfg = ArgusSafetyConfigC {
            t_high: config.t_high,
            t_low: config.t_low,
            degraded_velocity_scale: config.degraded_velocity_scale,
            degraded_force_scale: config.degraded_force_scale,
            hard_max_torque_nm: config.hard_max_torque_nm,
            hard_max_velocity_rad_s: config.hard_max_velocity_rad_s,
            persistence_windows: config.persistence_windows,
        };

        let handle = unsafe { argus_envelope_create(&cfg) };
        if handle.is_null() {
            return Err(ARGUS_INTERNAL_ERROR as c_int);
        }

        Ok(Self { handle })
    }

    /// Reset to SAFE_HALT state
    pub fn reset(&mut self) -> Result<(), c_int> {
        let result = unsafe { argus_envelope_reset(self.handle) };
        if result != ARGUS_OK as c_int {
            return Err(result);
        }
        Ok(())
    }

    /// Evaluate one window
    pub fn evaluate(
        &mut self,
        prediction: &Prediction,
        quality: &SignalQuality,
    ) -> Result<ActuatorCommand, c_int> {
        let intent_c = CString::new(prediction.intent.clone()).unwrap();
        let pred = ArgusPredictionC {
            intent: intent_c.as_ptr(),
            confidence: prediction.confidence,
        };

        let qual = ArgusSignalQualityC {
            reliability: quality.reliability,
            flatline_channels: quality.flatline_channels.as_ptr() as *mut u32,
            flatline_count: quality.flatline_channels.len(),
            artifact_detected: quality.artifact_detected as i32,
        };

        let mut cmd = ArgusActuatorCommandC {
            intent: ptr::null(),
            torque_nm: 0.0,
            velocity_rad_s: 0.0,
            envelope_state: 0,
            effective_confidence: 0.0,
            vetoed_by_supervisor: 0,
        };

        let result = unsafe { argus_envelope_evaluate(self.handle, &pred, &qual, &mut cmd) };
        if result != ARGUS_OK as c_int {
            return Err(result);
        }

        let intent = unsafe { CStr::from_ptr(cmd.intent).to_string_lossy().into_owned() };

        Ok(ActuatorCommand {
            intent,
            torque_nm: cmd.torque_nm,
            velocity_rad_s: cmd.velocity_rad_s,
            envelope_state: EnvelopeState::from(cmd.envelope_state),
            effective_confidence: cmd.effective_confidence,
            vetoed_by_supervisor: cmd.vetoed_by_supervisor != 0,
        })
    }

    /// Get current state
    pub fn state(&self) -> Result<EnvelopeState, c_int> {
        let mut state: i32 = 0;
        let result = unsafe { argus_envelope_get_state(self.handle, &mut state) };
        if result != ARGUS_OK as c_int {
            return Err(result);
        }
        Ok(EnvelopeState::from(state))
    }

    /// Get low streak count
    pub fn low_streak(&self) -> Result<u32, c_int> {
        let mut streak: u32 = 0;
        let result = unsafe { argus_envelope_get_low_streak(self.handle, &mut streak) };
        if result != ARGUS_OK as c_int {
            return Err(result);
        }
        Ok(streak)
    }
}

impl Drop for SafetyEnvelope {
    fn drop(&mut self) {
        if !self.handle.is_null() {
            unsafe { argus_envelope_destroy(self.handle) };
        }
    }
}

unsafe impl Send for SafetyEnvelope {}
unsafe impl Sync for SafetyEnvelope {}
