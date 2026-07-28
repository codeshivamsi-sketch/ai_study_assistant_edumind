// Thin entry — must not synchronously import anything that touches a shared
// module (react, react-dom, react-router-dom). The dynamic import() creates
// the async boundary webpack needs to initialize the Module Federation
// sharing scope before any shared module is required; a synchronous import
// here throws "Shared module is not available for eager consumption."
import("./bootstrap");
