from recipe_engine.recipe_api import Property

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/path',
    'recipe_engine/step',
    'build_api',
    'cros_version',
]

PROPERTIES = {
    # Google Storage bucket to upload artifacts to.
    'artifacts_gs_bucket':
        Property(kind=str, default='gs://chromeos-image-archive')
}
