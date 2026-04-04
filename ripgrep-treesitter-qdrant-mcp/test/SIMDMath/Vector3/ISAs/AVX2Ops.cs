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

        private sealed partial class Avx2Vector3Ops : IVector3Ops
        {
            internal static readonly Avx2Vector3Ops Instance = new Avx2Vector3Ops();
            private Avx2Vector3Ops() { }
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add(Span<Vector3> left, ReadOnlySpan<Vector3> right) => AddVector3ScalarEntry(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add(Span<Vector3> left, Vector3 value) => AddVector3ScalarConstEntry(left, value);
        }
    }
}