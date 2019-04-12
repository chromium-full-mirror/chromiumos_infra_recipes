DEPS = ['recipe_engine/cipd', 'recipe_engine/step', 'recipe_engine/swarming']

from recipe_engine.recipe_api import Property
from recipe_engine.config import ConfigGroup, Single

PROPERTIES = {
    '$chromeos/vm_test':
        Property(
            help='Properties specifically for the chromeos vm_test module.',
            param_name='vm_test_properties',
            kind=ConfigGroup(
                # The absolute path to the temporary directory that the recipe should use.
                swarming_server=Single(str),
                swarming_pool=Single(str),
            ),
            default={},
        )
}
