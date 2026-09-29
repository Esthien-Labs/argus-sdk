// build.rs - Build script for Argus SDK Rust wrapper
// Generates FFI bindings from the C ABI header

use std::env;
use std::path::PathBuf;

fn main() {
    // Tell cargo to look for shared libraries in the lib directory
    let manifest_dir = env::var("CARGO_MANIFEST_DIR").unwrap();
    let lib_dir = PathBuf::from(manifest_dir).join("lib");
    println!("cargo:rustc-link-search={}", lib_dir.display());

    // Link against the Argus native library
    #[cfg(target_os = "windows")]
    println!("cargo:rustc-link-lib=argus");
    #[cfg(target_os = "macos")]
    println!("cargo:rustc-link-lib=argus");
    #[cfg(target_os = "linux")]
    println!("cargo:rustc-link-lib=argus");

    // Generate bindings
    let bindings = bindgen::Builder::default()
        .header("include/argus.h")
        .parse_callbacks(Box::new(bindgen::CargoCallbacks::new()))
        .generate()
        .expect("Unable to generate bindings");

    let out_path = PathBuf::from(env::var("OUT_DIR").unwrap());
    bindings
        .write_to_file(out_path.join("bindings.rs"))
        .expect("Couldn't write bindings!");
}
