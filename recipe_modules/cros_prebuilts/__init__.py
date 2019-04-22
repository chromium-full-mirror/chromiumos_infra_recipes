from recipe_engine.recipe_api import Property

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/runtime',
    'recipe_engine/step',
    'build_api',
    'cros_source',
    'cros_version',
    'git',
    'git_txn',
    'repo',
]

PROPERTIES = {
    # Google Storage bucket to upload prebuilts to.
    # TODO(crbug.com/953899): Remove default once property is set in config.
    'prebuilts_gs_bucket': Property(kind=str, default='gs://chromeos-prebuilt')
}
