using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;

namespace MyProject
{
    public static partial class SIMDMath
    {

        private sealed partial class ScalarVector3Ops : IVector3Ops
        {
            internal static readonly ScalarVector3Ops Instance = new ScalarVector3Ops();
            private ScalarVector3Ops() { }
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add(Span<Vector3> left, ReadOnlySpan<Vector3> right) => AddVector3ScalarEntry(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add(Span<Vector3> left, Vector3 value) => AddVector3ScalarConstEntry(left, value);
        }
    }
}