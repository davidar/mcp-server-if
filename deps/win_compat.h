/*
 * win_compat.h - POSIX compatibility shims for MinGW-w64 (UCRT64)
 *
 * Injected via gcc -include to bridge POSIX APIs used by RemGlk
 * without patching submodule source files.
 *
 * UCRT64 provides timespec_get/TIME_UTC natively (C11).
 * gmtime_r/localtime_r are enabled via -D_POSIX_THREAD_SAFE_FUNCTIONS.
 */

#ifdef _WIN32

#include <stdlib.h>
#include <string.h>

/* random()/srandom() -> rand()/srand() (rgwindow.c, rgfref.c, rgstream.c) */
#define random() ((long)rand())
#define srandom(seed) srand((unsigned int)(seed))

/* bzero() -> memset() (cgdate.c) */
#define bzero(ptr, len) memset((ptr), 0, (len))

/* timegm() -> _mkgmtime() (cgdate.c) */
#define timegm(tm) _mkgmtime(tm)

#endif /* _WIN32 */
