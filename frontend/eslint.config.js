export default [
  {
    rules: {
      'no-restricted-imports': ['error', {
        patterns: [{
          group: ['**/lib/supabase'],
          message: "Import from 'lib/supabaseAuth' instead — direct supabase.auth.* calls have no timeout and can hang on internal lock contention.",
        }],
      }],
    },
  },
  {
    // Exempt the wrapper itself, which legitimately imports the supabase client.
    files: ['src/lib/supabaseAuth.js'],
    rules: { 'no-restricted-imports': 'off' },
  },
]
