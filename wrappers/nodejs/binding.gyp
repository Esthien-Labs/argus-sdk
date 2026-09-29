{
  "targets": [
    {
      "target_name": "argus",
      "sources": ["src/argus.cc"],
      "include_dirs": ["<!(node -p \"require('node-addon-api').include_dir\")"],
      "libraries": ["<(module_root_dir)/lib/argus.lib"],
      "defines": ["NAPI_DISABLE_CPP_EXCEPTIONS"],
      "conditions": [
        ["OS=='win'", {
          "libraries": ["<(module_root_dir)/lib/argus.lib"]
        }],
        ["OS=='mac'", {
          "libraries": ["<(module_root_dir)/lib/libargus.dylib"]
        }],
        ["OS=='linux'", {
          "libraries": ["<(module_root_dir)/lib/libargus.so"]
        }]
      ]
    }
  ]
}
