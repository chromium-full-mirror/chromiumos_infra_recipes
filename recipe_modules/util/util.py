# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utility methods available to recipes and recipe modules.

"""

from collections import namedtuple
import datetime
import functools
import random
import time

# Give this back as a default, creating a simple named tuple without tests
# enabled.
_NO_TEST_DATA = namedtuple('_NO_TEST_DATA', 'enabled')
_NO_TEST_DATA.__new__.__defaults__ = (False,)

# Shamelessly stolen from recipe_engine/util.py, which we should not be using.
# This differs in that it does not call logging.exception.
class exponential_retry():
  """Decorator which retries the function if an exception is encountered."""

  def __init__(self, retries=None, delay=None, condition=None):
    """Creates a new exponential retry decorator.

    Args:
      retries (int): Maximum number of retries before giving up.
      delay (datetime.timedelta): Amount of time to wait before retrying. This
          will double every retry attempt (exponential).
      condition (func): If not None, a function that will be passed the
          exception as its one argument. Retries will only happen if this
          function returns True. If None, retries will always happen.
    """
    self.retries = retries or 5
    self.delay = delay or datetime.timedelta(seconds=1)
    self.condition = condition or (lambda e: True)

  def __call__(self, f):

    @functools.wraps(f)
    def wrapper(*args, **kwargs):  # pylint: disable=inconsistent-return-statements
      retry_delay = self.delay
      for i in range(self.retries):
        try:
          return f(*args, **kwargs)
        except Exception as e:  # pylint: disable=broad-except
          if (i + 1) >= self.retries or not self.condition(e):
            raise
          # Detect running in a testing context and elide the sleep itself.
          #
          # Do this by pulling out the first argument (should be 'self', then
          # trying to snag the testing enablement flag. If this fails just
          # use the _NO_TEST_DATA default which defines tests as not being
          # enabled and do the sleep.
          if not args or args and not getattr(
              getattr(args[0], '_test_data', _NO_TEST_DATA), 'enabled', True):
            time.sleep(retry_delay.total_seconds())  # pragma: nocover

          # Add jitter to retries 2x +- 12.5%.
          new_retry_ms = retry_delay.total_seconds() * (2 + ((
              (random.random() - 0.5)) / 2.0)) * 1000.0
          retry_delay = datetime.timedelta(milliseconds=new_retry_ms)

    return wrapper
