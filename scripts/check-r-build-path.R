paths <- commandArgs(trailingOnly = TRUE)
if (!length(paths)) paths <- c(R.home(), Sys.getenv("R_LIBS_USER"))
paths <- normalizePath(paths, winslash = "/", mustWork = TRUE)
non_ascii <- vapply(paths, function(path) any(utf8ToInt(enc2utf8(path)) > 127L), logical(1))
if (any(non_ascii)) {
  stop(paste(
    "Rtools cannot link libraries in a non-ASCII physical path.",
    "Use a real ASCII checkout for source builds; junctions and subst are resolved back",
    "to their original paths by R. Pinned dependency versions must remain unchanged."
  ), call. = FALSE)
}
cat("R source-build paths are ASCII.\n")
