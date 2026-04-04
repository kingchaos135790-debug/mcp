using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.Intrinsics.X86;
using System.Threading.Tasks;

namespace MyProject
{
    public static partial class SIMDMath
    {
        private static IFloatOps s_fpOps = ScalarFloatOps.Instance; // default fallback until initialized
        private static IVector3Ops s_v3Ops = ScalarVector3Ops.Instance; // default fallback until initialized
        private const int Avx2Unroll = 32, AvxUnroll = 32, SseUnroll = 16, Sse41Unroll = 16;
        // Public initializers: allow callers to force a specific implementation.
        // Useful for testing, benchmarking, or controlling ISA selection.
        public static void Avx2Initialize()
        {
            s_fpOps = Avx2FloatOps.Instance;
            s_v3Ops = Avx2Vector3Ops.Instance;
        }

        public static void AvxInitialize()
        {
            s_fpOps = AvxFloatOps.Instance;
            s_v3Ops = Avx2Vector3Ops.Instance; // AVX2 is required for Vector3 ops
        }

        public static void Sse41Initialize()
        {
            s_fpOps = Sse41FloatOps.Instance;
        }

        public static void Sse2Initialize()
        {
            s_fpOps = Sse2FloatOps.Instance;
        }

        public static void ScalarInitialize()
        {
            s_fpOps = ScalarFloatOps.Instance;
        }

        // Selects the best available ISA at runtime. This mirrors the static ctor behavior
        // but can be invoked manually to re-check feature availability.
        public static void InitializeBest()
        {
            if (Avx2.IsSupported)
                Avx2Initialize();
            else if (Avx.IsSupported)
                AvxInitialize();
            else if (Sse41.IsSupported)
                Sse41Initialize();
            else if (Sse2.IsSupported)
                Sse2Initialize();
            else
                ScalarInitialize();
        }

        static SIMDMath() => InitializeBest();
    }
}