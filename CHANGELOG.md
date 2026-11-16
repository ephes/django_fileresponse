# Changelog

## Unreleased

- Acquire filesystem and S3 sources before sending headers; refuse non-regular
  local files without blocking, and close acquired sources on header-send errors.
