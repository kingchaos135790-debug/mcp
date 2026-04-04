using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;

namespace MyProject
{
    public static partial class SIMDMath
    {
        private sealed partial class ScalarFloatOps : IFloatOps
        {
            internal static readonly ScalarFloatOps Instance = new ScalarFloatOps();
            private ScalarFloatOps() { }
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => AddFloatScalar_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, float value) => AddFloatScalarConst_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => SubFloatScalar_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, float value) => SubFloatScalarConst_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => MulFloatScalar_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, float value) => MulFloatScalarConst_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => DivFloatScalar_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, float value) => DivFloatScalarConst_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend) => FmaFloatScalar_2xUnroll(left, multiplicand, addend);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, float multiplicand, float addend) => FmaFloatScalarConst_2xUnroll(left, multiplicand, addend);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Exp(Span<float> values) => ExpFloatScalar(values);

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Exp(Span<float> values, Span<float> result) => ExpFloatScalar(values, result);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                AddFloatScalar_2xUnroll(left, right, result);
            }
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                AddFloatScalarConst_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                SubFloatScalar_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                SubFloatScalarConst_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                MulFloatScalar_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                MulFloatScalarConst_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                DivFloatScalar_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                DivFloatScalarConst_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend, Span<float> result)
            {
                FmaFloatScalar_2xUnroll(left, multiplicand, addend, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, float multiplicand, float addend, Span<float> result)
            {
                FmaFloatScalarConst_2xUnroll(left, multiplicand, addend, result);
            }
        }
    }
}