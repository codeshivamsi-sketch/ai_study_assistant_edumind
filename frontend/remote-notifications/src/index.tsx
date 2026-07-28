// Thin entry — see frontend/CONTRACTS.md's webpack gotcha #1. Must not
// synchronously import anything that touches a shared module.
import("./bootstrap");
