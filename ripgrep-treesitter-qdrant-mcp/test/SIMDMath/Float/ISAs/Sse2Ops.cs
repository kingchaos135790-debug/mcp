using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;

namespace MyProject
{
    public static partial class SIMDMath
    {
        private sealed partial class Sse2FloatOps : IFloatOps
        {
            internal static readonly Sse2FloatOps Instance = new Sse2FloatOps();
            private Sse2FloatOps() { }
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => AddFloatSse2_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, float value) => AddFloatSse2Const_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => SubFloatSse2_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, float value) => SubFloatSse2Const_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => MulFloatSse2_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, float value) => MulFloatSse2Const_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, ReadOnlySpan<float> right) => DivFloatSse2_2xUnroll(left, right);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, float value) => DivFloatSse2Const_2xUnroll(left, value);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend) => FmaFloatSse2_2xUnroll(left, multiplicand, addend);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, float multiplicand, float addend) => FmaFloatSse2Const_2xUnroll(left, multiplicand, addend);
            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Exp(Span<float> values) => ExpFloatSse2(values);

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                AddFloatSse2_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Add_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                AddFloatSse2Const_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                SubFloatSse2_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Sub_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                SubFloatSse2Const_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                MulFloatSse2_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Mul_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                MulFloatSse2Const_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result)
            {
                DivFloatSse2_2xUnroll(left, right, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Div_2xUnroll(Span<float> left, float value, Span<float> result)
            {
                DivFloatSse2Const_2xUnroll(left, value, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend, Span<float> result)
            {
                FmaFloatSse2_2xUnroll(left, multiplicand, addend, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Fma_2xUnroll(Span<float> left, float multiplicand, float addend, Span<float> result)
            {
                FmaFloatSse2Const_2xUnroll(left, multiplicand, addend, result);
            }

            [MethodImpl(MethodImplOptions.AggressiveInlining)]
            public void Exp(Span<float> values, Span<float> result)
            {
                ExpFloatSse2(values, result);
            }
        }
    }
}