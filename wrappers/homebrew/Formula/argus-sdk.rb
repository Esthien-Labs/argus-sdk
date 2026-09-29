# Homebrew tap for Argus SDK
# This file defines the formula for installing Argus SDK via Homebrew

class ArgusSdk < Formula
  desc "Argus SDK - Safety-supervised inference for physical systems"
  homepage "https://esthien.com"
  version "0.7.3"
  license :cannot_represent

  # URLs for the released artifacts
  on_macos do
    on_intel do
      url "https://github.com/Esthien-Labs/argus-sdk/releases/download/v0.7.3/argus-sdk-0.7.3-macos-x64.pkg"
      sha256 "PLACEHOLDER_SHA256_X64"
    end
    on_arm do
      url "https://github.com/Esthien-Labs/argus-sdk/releases/download/v0.7.3/argus-sdk-0.7.3-macos-arm64.pkg"
      sha256 "PLACEHOLDER_SHA256_ARM64"
    end
  end

  def install
    # The .pkg installer is a self-contained package
    # We extract and install the binary
    system "pkgutil", "--expand-full", cached_download, "pkg"

    # Install the binary
    bin.install "pkg/Payload/usr/local/bin/argus"

    # Install documentation
    doc.install "README.md" if File.exist?("README.md")
  end

  def caveats
    <<~EOS
      Argus SDK has been installed to:
        #{bin}/argus

      To verify installation:
        argus --version
        argus runtime-info

      For more information:
        https://esthien.com/docs/argus-sdk
    EOS
  end

  test do
    assert_match "argus #{version}", shell_output("#{bin}/argus --version")
  end
end
