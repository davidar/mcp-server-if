// Custom RemGlk startup for bocfel.
// Hardcodes autosave with library state for singleturn operation.
//
// Replaces garglk's terps/bocfel/glkstart.cpp at compile time.

#include <cstdlib>
#include <initializer_list>
#include <string>

#include "options.h"
#include "screen.h"
#include "types.h"
#include "zterp.h"

extern "C" {
#include <glk.h>
#include <glkstart.h>
}

#ifdef ZTERP_GLK_BLORB
extern "C" {
#include <gi_blorb.h>
}
#endif

// glkunix_arguments[] is populated by the Options constructor in
// options.cpp (the ZTERP_GLK_UNIX block). It registers all of bocfel's
// single-char flags plus a positional game-file entry.
// We just need to provide the storage.
glkunix_argumentlist_t glkunix_arguments[128] = {
    { nullptr, glkunix_arg_End, nullptr }
};

// Blorb resource loading — copied from garglk's glkstart.cpp (MIT).
static void load_resources()
{
#ifdef ZTERP_GLK_BLORB
    auto load_file = [](const std::string &file, StreamRock rock) -> strid_t {
        return glkunix_stream_open_pathname(
            const_cast<char *>(file.c_str()), 0, static_cast<glui32>(rock));
    };

    auto set_map = [&load_file](const std::string &blorb_file) {
        strid_t file = load_file(blorb_file, StreamRock::BlorbStream);
        if (file != nullptr) {
            if (giblorb_set_resource_map(file) == giblorb_err_None) {
                screen_load_scale_info(blorb_file);
                return true;
            }
            glk_stream_close(file, nullptr);
        }
        return false;
    };

    if (set_map(game_file)) {
        return;
    }

    for (const auto &ext : {".blb", ".blorb"}) {
        std::string blorb_file = game_file;
        auto dot = blorb_file.rfind('.');
        if (dot != std::string::npos) {
            blorb_file.replace(dot, std::string::npos, ext);
        } else {
            blorb_file += ext;
        }
        if (set_map(blorb_file)) {
            return;
        }
    }
#endif
}

int glkunix_startup_code(glkunix_startup_t *data)
{
    // Always enable autosave with RemGlk library state.
    options.autosave = true;
    options.autosave_librarystate = true;

    // Read autosave directory from environment. The Python server sets
    // this before spawning bocfel.
    const char *autodir = std::getenv("BOCFEL_AUTOSAVE_DIRECTORY");
    if (autodir != nullptr) {
        options.autosave_directory = std::make_unique<std::string>(autodir);
    }

    options.process_arguments(data->argc, data->argv);

    if (arg_status.any() || options.show_version || options.show_help) {
        return 1;
    }

    // Called by RemGlk on -singleturn shutdown; must finalize Glk
    // streams before they are closed.
    glk_set_interrupt_handler(screen_clean_up_glk_streams);

    if (!game_file.empty()) {
#ifndef ZTERP_OS_DOS
        glkunix_set_base_file(&game_file[0]);
#endif
        load_resources();
    }

    return 1;
}
