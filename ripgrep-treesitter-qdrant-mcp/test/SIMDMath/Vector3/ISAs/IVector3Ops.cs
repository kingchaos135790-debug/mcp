using System.Numerics;

namespace MyProject
{
    public static partial class SIMDMath
    {
        // Strategy interface implemented by hardware-specific singletons
        // Singletons per ISA. Each simply forwards to the static intrinsic entry points
        private interface IVector3Ops
        {
            void Add(Span<Vector3> left, ReadOnlySpan<Vector3> right);
            void Add(Span<Vector3> left, Vector3 value);
        }

    }
}