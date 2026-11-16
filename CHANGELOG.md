# Changelog

## Unreleased

- Acquire filesystem and S3 sources before sending headers; refuse non-regular
  local files without blocking, and close acquired sources on header-send errors.
- Refuse sequential and concurrent response reuse before headers with a stable
  error, preserving legacy helper delegation and middleware transformations.
- Forward Django status, reason, content type, charset and headers consistently
  from both adapters while keeping S3 connection options separate.
- Populate safe source type and length during admission, preserving explicit
  caller metadata and omitting source length for middleware-transformed bodies.
- Refuse successful transfer completion when original source bytes differ from
  the admitted length, including under compression and explicit HTTP overrides.
