# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utility methods available to recipes and recipe modules.

"""

import datetime
import functools
import time


# Shamelessly stolen from recipe_engine/util.py, which we should not be using.
# This differs in that it does not call logging.exception.
class exponential_retry(object):
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
    def wrapper(*args, **kwargs):
      retry_delay = self.delay
      for i in xrange(self.retries):
        try:
          return f(*args, **kwargs)
        except Exception as e:
          if (i + 1) >= self.retries or not self.condition(e):
            raise
          time.sleep(retry_delay.total_seconds())
          retry_delay *= 2

    return wrapper
