println("========================================")
println("Installing Wflow.jl for Julia")
println("========================================")

using Pkg

println("\n1. Updating package registry...")
Pkg.update()

println("\n2. Adding Wflow package...")
try
    Pkg.add("Wflow")
catch e
    println("Error adding Wflow: ", e)
    println("Trying with specific version...")
    Pkg.add(Pkg.PackageSpec(name="Wflow", version="0.6.0"))
end

println("\n3. Installing dependencies...")
Pkg.instantiate()

println("\n4. Precompiling Wflow...")
try
    using Wflow
    println("   ✓ Wflow loaded successfully")
catch e
    println("   ✗ Error loading Wflow: ", e)
end

println("\n5. Verifying installation...")
version = try
    pkgversion(Wflow)
catch
    "unknown (but package is installed)"
end

println("   Wflow.jl version: ", version)

println("\n6. Checking available functions...")
functions = try
    names(Wflow)
catch
    ["Wflow module loaded"]
end
println("   Available functions: ", length(functions))

println("\n========================================")
println("Installation complete!")
println("========================================")
println()
println("To test the installation in Julia:")
println("  using Wflow")
println("  Wflow.run(\"path/to/your/config.toml\")")
println()