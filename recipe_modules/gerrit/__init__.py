DEPS = {
    'depot_tools_gerrit': 'depot_tools/gerrit',
    'buildbucket': 'recipe_engine/buildbucket',
    'context': 'recipe_engine/context',
    'json': 'recipe_engine/json',
    'path': 'recipe_engine/path',
    'raw_io': 'recipe_engine/raw_io',
    'step': 'recipe_engine/step',
    'git': 'git',
    'git_cl': 'git_cl',
    'support': 'support',

    # TODO(evanhernandez): This is a significant code smell.
    # A Gerrit module should know nothing about ChromeOS.
    # Remove these dependencies once we find a better REST
    # client interface.
    'cros_source': 'cros_source',
    'repo': 'repo',
}
