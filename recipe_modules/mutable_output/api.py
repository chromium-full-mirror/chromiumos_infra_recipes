# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tooling to support output properties that can mutate during a build.

This is intended to be used with the following pattern:

At the earliest stage in your recipe (ideally at the beginning of RunSteps),
wrap everything in the context:

```
with api.mutable_output.wrap():
  # the rest of the build...
```

From that point on, you can feel free to add output properties to the build from
*anywhere* in the stack:

```
api.mutable_output(foo='bar')
```

When the build finishes, either successfully or with exceptions, the properties
sent to this module will be emitted as output properties of the build.
"""

import contextlib
from typing import Dict

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure


class MutableOutputApi(recipe_api.RecipeApi):
  """A module for mutable output properties."""

  def __init__(self, *args, **kwargs) -> None:
    """Set up initial state."""
    super().__init__(*args, **kwargs)
    self._props = None

  @contextlib.contextmanager
  def wrap(self) -> None:
    if self._props is not None:
      raise StepFailure(
          'MutableOutput module only supports one layer of wrapping.')
    self._props = {}
    try:
      yield
    finally:
      self.m.easy.set_properties_step(step_name='set mutable output properties',
                                      **self._props)
      self._props = None

  @property
  def props(self) -> Dict:
    """Get existing props."""
    return self._props

  def __call__(self, **kwargs) -> None:
    self._props.update(kwargs)
