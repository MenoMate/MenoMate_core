Perform only a final authentication/documentation cleanup pass.

Do not redesign the project.
Do not add new architecture.
Do not add new dependencies unless strictly necessary.

1. Review app/core/security.py.

Make JWT validation strict:

- Explicitly reject unsupported algorithms.
- Do not silently route unknown algorithms into the HS256 branch.
- Require the issuer claim.
- Require the audience claim.
- Require audience == "authenticated" for real Supabase tokens.
- Require issuer == "{SUPABASE_URL}/auth/v1" for real Supabase tokens.
- Continue validating exp and sub.
- Continue validating the cryptographic signature.
- Keep RS256/ES256 JWKS support if implemented.
- Keep HS256 support only for projects actually configured for symmetric signing.

Tests may continue using controlled test tokens, but do not weaken production validation merely to accommodate tests.

2. Update README.md:

- Change "32 tests" to "34 tests" if that is the verified current count.
- Clarify that SUPABASE_JWT_SECRET is used for legacy/symmetric HS256 verification when applicable.
- Change "PID-regulated thermal delivery" to a technology-neutral description because the ESP32 firmware is not implemented yet.
- Keep the existing Demo section.
- Keep "Live Demo: Coming soon".
- Do not invent URLs.

3. Run the complete test suite.

4. Verify:
- 34 tests pass
- no Firebase references
- no Firestore references
- no fake GitHub URL
- no secrets
- no old React/web references
- README endpoint list still matches OpenAPI

Do not make any unrelated changes.

Report exactly what changed and the final test result.