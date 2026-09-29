# config/profiles/regression/

Controller regression evaluation profiles for use with `atlas regression-eval`.

These profiles use the `controller_regression_v0` schema, which is distinct from
the `PartnerProfile` (assistive controller) schema used by `atlas compile` and
`atlas safety-case`. They are intentionally stored in this subdirectory so the
PAT-002 conformance harness does not scan them.

## Reference Profiles

| File | Interface type | Safety standard | Use case |
|---|---|---|---|
| `robot_diff_drive_ros2_v0.json` | `ros2_diff_drive` | ISO 3691-4:2023, IEC 61508:2010 | ROS 2 Nav2 AMR / warehouse robot |
| `automotive_ecu_can_v0.json` | `can_bus_torque` | ISO 26262:2018 ASIL-C, IEC 61508:2010 | CAN bus automotive ECU |
| `industrial_cobot_joint_v0.json` | `proprietary_spi` | ISO 10218-1:2011 PLd, ISO/TS 15066:2016 | SPI cobot joint controller |

## Usage

```powershell
# Run with synthetic trace (no customer data needed)
atlas regression-eval --sample --profile config/profiles/regression/robot_diff_drive_ros2_v0.json

# Run with real trace
atlas regression-eval --trace trace.json --profile config/profiles/regression/robot_diff_drive_ros2_v0.json
```

## Schema

The schema is defined and validated in `src/atlas/regression/schema.py`.
Profile format: `controller_regression_v0`. Required fields: `schema_version`,
`profile_id`, `producer_config`, `receiver_config`, `command_limits`,
`fault_corpus`, `applicable_standards`.
