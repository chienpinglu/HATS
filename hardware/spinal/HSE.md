# HSE compatibility entry points

HATS Scalar Engine has been renamed **Application Processing Engine (APE)**.
See [APE](APE.md) for the implementation, specification and verification status.

`HseCore(HseConfig(...))` delegates to `ApeCore` with prediction disabled, matching
the initial fall-through behavior. `GenerateHse` still emits `HseCore.v` under
`build/hse/rtl/r*/`. Internal decoder and operation names are not compatibility APIs.

The old `assemble_hse.py` and `verify_hse.py` commands delegate to the APE tools;
their new outputs are under `build/ape/`, not `build/hse/`. `HseCoreSim N`
delegates to `ApeCoreSim N off`. Historical HSE reports are not current APE evidence.
