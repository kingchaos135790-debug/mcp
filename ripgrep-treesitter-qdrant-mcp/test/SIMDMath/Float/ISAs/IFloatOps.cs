using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;

namespace MyProject
{
    public static partial class SIMDMath
    {
        // Strategy interface implemented by hardware-specific singletons
        // Singletons per ISA. Each simply forwards to the static intrinsic entry points
        private interface IFloatOps
        {
            void Add_2xUnroll(Span<float> left, ReadOnlySpan<float> right);
            void Add_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result);
            void Add_2xUnroll(Span<float> left, float value);
            void Add_2xUnroll(Span<float> left, float value, Span<float> result);
            void Sub_2xUnroll(Span<float> left, ReadOnlySpan<float> right);
            void Sub_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result);
            void Sub_2xUnroll(Span<float> left, float value);
            void Sub_2xUnroll(Span<float> left, float value, Span<float> result);
            void Mul_2xUnroll(Span<float> left, ReadOnlySpan<float> right);
            void Mul_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result);
            void Mul_2xUnroll(Span<float> left, float value);
            void Mul_2xUnroll(Span<float> left, float value, Span<float> result);
            void Div_2xUnroll(Span<float> left, ReadOnlySpan<float> right);
            void Div_2xUnroll(Span<float> left, ReadOnlySpan<float> right, Span<float> result);
            void Div_2xUnroll(Span<float> left, float value);
            void Div_2xUnroll(Span<float> left, float value, Span<float> result);
            // FMA semantics: left[i] = left[i] * multiplicand[i] + addend[i]
            void Fma_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend);
            void Fma_2xUnroll(Span<float> left, ReadOnlySpan<float> multiplicand, ReadOnlySpan<float> addend, Span<float> result);
            void Fma_2xUnroll(Span<float> left, float multiplicand, float addend);
            void Fma_2xUnroll(Span<float> left, float multiplicand, float addend,Span<float> result);
            // In-place exponential: left[i] = Exp(left[i])
            void Exp(Span<float> values);
            void Exp(Span<float> values, Span<float> result);
        }

    }
}