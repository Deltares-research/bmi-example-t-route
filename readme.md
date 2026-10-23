# T-Route for Delft-FEWS

This is a fork of [NOAA-OWP/T-Route](https://github.com/NOAA-OWP/t-route),
adapted for interoperability with Delft-FEWS through the Basic Model Interface
(BMI). It builds on T-Route's existing BMI interfaces; BMI itself is not new to
this fork.

The main work in this fork is:

1. **Compile T-Route for use through BMI**, with the dependencies and routing
   adaptations needed to run the model through that interface.
2. **Create a runnable BMI smoke test**, using a three-segment model that is
   also supported in Delft-FEWS through the FEWS-BMI adaptor.

This README focuses on the Delft-FEWS use case. For native T-Route capabilities,
routing methods, installation, and examples, use the
[original NOAA documentation](https://github.com/NOAA-OWP/t-route/blob/master/readme.md).

## How the Delft-FEWS connection works

The **FEWS-BMI adaptor is the coupling driver** between Delft-FEWS and one
T-Route BMI instance. It supplies lateral inflows by river-segment ID, advances
the model, and reads the routed results:

```text
Delft-FEWS lateral inflows -> FEWS-BMI adaptor -> T-Route BMI
Delft-FEWS results        <- FEWS-BMI adaptor <- discharge, velocity, depth
```

T-Route reads the static network geometry and attributes from a GeoPackage.
The time-varying lateral inflows are supplied through BMI rather than read by
T-Route from its native forcing files.

The model-side sequence is:

1. Initialize T-Route with the BMI configuration.
2. Set the segment IDs and lateral inflows through BMI.
3. Advance one routing time step with `update()` (300 s in the example).
4. Read discharge, velocity, and depth, then repeat for the next time step.
5. Finalize the model.

Lateral inflows must be supplied at the model time step, one value per
`update()`; the number of updates sets the run length. See
[time stepping](test/fews-bmi-smoke-test/README.md#time-stepping) in the test
guide for details and current `update_until()` limitations.

The FEWS-BMI adaptor configuration and data exchange setup will be documented
in a future integration guide. The runnable example below checks the T-Route
side independently of Delft-FEWS.

## Coupling scope and limitations

- **Lateral inflows only.** The current setup supplies lateral inflows by
  river-segment ID. Inflow supplied to the most upstream segment is still
  lateral inflow, not a separately prescribed external upstream discharge.
- **No external boundary coupling.** Separately prescribed upstream discharge
  and downstream/coastal water-level boundaries are outside this setup.
- **Cold-start example.** The smoke test starts with zero channel flow and
  depth; save/restore and warm-restart equivalence have not been verified.
- **Model-side interface check.** The smoke test does not run the
  FEWS-BMI adaptor or Delft-FEWS, and is not an end-to-end integration test or
  scientific validation. Comparing its results with an adaptor run of the same
  inputs checks the coupling.

These limits describe the current Delft-FEWS setup and smoke test, not all
native T-Route capabilities. See the
[test guide](test/fews-bmi-smoke-test/README.md#boundary-conditions-and-warm-state-limitations)
for details.

## What this fork adds

- Adaptations to the existing BMI routing path, including the missing routing
  arguments needed by the example.
- A FEWS-BMI smoke test with synthetic lateral inflows, using the same three-segment
  model and input/work/output folder layout as the Delft-FEWS integration. Its
  results are the reference for comparing a FEWS-BMI adaptor run with the same inputs.
- A [test guide](test/fews-bmi-smoke-test/README.md) covering the model, input/output
  contract, and current limitations.
- An [automated Ubuntu build and BMI test](.github/workflows/fews-bmi-smoke-test.yml).

## Run the model locally and in Delft-FEWS

The [FEWS-BMI smoke-test folder](test/fews-bmi-smoke-test) contains the example
model and configuration (`work/`), synthetic lateral inflows (`input/`), and
driver. Follow its
[setup and run guide](test/fews-bmi-smoke-test/README.md#3-manually-compile-and-run-the-model)
to build this fork and run the test without Delft-FEWS.

**Delft-FEWS integration guide: to be added.** It will describe how to configure the
FEWS-BMI adaptor for lateral-inflow coupling and run the same model from
Delft-FEWS. Until then, use the local smoke test to verify the T-Route build
and model-side BMI exchange.

## Licensing and attribution

T-Route originates from NOAA's Office of Water Prediction and its contributors.
See the [original project](https://github.com/NOAA-OWP/t-route) for credits and
references. The repository's [terms](TERMS.md) and [license](LICENSE) apply.
