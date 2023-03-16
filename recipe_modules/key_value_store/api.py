# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to interact with key-value store files.

Key-value stores are used commonly by Chromite, including some locations in our
codebase and in our Google Storage files.

Key-value store files comprise a series of key="value" pairs, each on distinct
lines. Values can span multiple lines; they end when they reach a line that ends
with the same quote character (' or ") that started the value. Lines may be
blank. Comments are lines beginning with "#". Any line may also begin with
whitespace, and there may be whitespace surrounding the "=".

Below is a sample valid key-value store.

    # Copyright 2023 The ChromiumOS Authors
    # Etc etc etc
    simple_value_1="hello"
        simple_value_2   =\t'hello'
    simple_value_3 = "I contain an internal quote (")!"

    multiline_1 = "Hello,
    world!"

    multiline_2 = "Mismatched end quote: '
    That didn't end the value because it didn't match the starting quote."

    multiline_3 = "Check this one out...
    not_really_a_value = 'Did I fool you?'
    The above line wasn't parsed because it's part of a value."

Note: If you're designing a new data store, please use JSON rather than this
format. This library is designed to work with legacy/external files where JSON
isn't an option.
"""

import collections
import json
from typing import Optional, OrderedDict

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure


class KeyValueStoreApi(RecipeApi):

  def parse_contents(self, contents: str,
                     source: str = '') -> OrderedDict[str, str]:
    """Return the contents of a key-value store interpreted as a dict.

    Args:
      contents: The complete contents of the key-value store.
      source: Optional string describing where the contents came from. If
        provided, this will be included in the step name.

    Returns:
      A dictionary of {key: value} containing the key-values from contents, in
      the order that the keys were found.
    """
    QUOTE_CHARS = ('"', "'")
    step_name = 'parse key-value store'
    if source:
      step_name = f'{step_name} from {source}'
    result: OrderedDict[str, str] = collections.OrderedDict()
    with self.m.step.nest(step_name) as presentation:
      # current_multiline_quote_char and current_multiline_key are used to track
      # values that span multiple lines.
      # current_multiline_quote_char holds the character that started the value:
      # either " or '.
      # current_multiline_key holds the key that the value is for.
      # When not parsing a multi-line value, both should be None.
      current_multiline_quote_char: Optional[str] = None
      current_multiline_key: Optional[str] = None

      def _is_in_multiline() -> bool:
        """Check whether we're in the middle of a multiline value."""
        assert ((current_multiline_key is None) == (current_multiline_quote_char
                                                    is None))
        return current_multiline_key is not None

      for line in contents.split('\n'):
        stripped_line = line.strip()
        if _is_in_multiline():
          # If we're in the middle of a multiline value, continue parsing it.
          if stripped_line.endswith(current_multiline_quote_char):
            # End the multiline value.
            # Only rstrip(), since whitespace on the left is part of the value.
            result[current_multiline_key] += line.rstrip()[:-1]
            current_multiline_key = None
            current_multiline_quote_char = None
          else:
            # Continue the multiline value.
            # Don't strip, since whitespace is part of the value.
            result[current_multiline_key] += line + '\n'
        else:
          # We're not in the middle of a multiline value.
          if stripped_line.startswith('#'):
            continue
          if not stripped_line:
            continue
          if '=' not in line:
            raise StepFailure(f'Invalid line (no assignment): {line}')
          key_part, value_part = line.split('=')
          key = key_part.strip()
          quote_char = value_part.strip()[0]
          if quote_char not in QUOTE_CHARS:
            raise StepFailure(f'Invalid line (bad quote char): {line}')
          if value_part.strip()[-1] == quote_char:
            # Single-line value.
            value = value_part.strip()[1:-1]
            result[key] = value
          else:
            # Begin a multi-line value.
            # Only lstrip(), since whitespace on the right is part of the value.
            value = value_part.lstrip()[1:]
            result[key] = value + '\n'
            current_multiline_key = key
            current_multiline_quote_char = quote_char
      if _is_in_multiline():
        raise StepFailure(f'Unterminated value (key={key}): {contents}.*')
      presentation.logs['parsed data'] = json.dumps(result, indent=4)
    return result
