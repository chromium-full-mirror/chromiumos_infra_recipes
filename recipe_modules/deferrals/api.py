# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for deferring things (mainly failures).

Usage:

# context mode:
with api.deferrals.raise_exceptions_at_end():
  with api.deferrals.defer_exceptions():
    do_a_thing_that_raises_an_exception()
  do_another_thing_that_should_happen_regardless()
# exception raised at this point

# explicit mode:
api.deferrals.defer_exception(StepFailure('error'))
do_another_thing_that_should_happen_regardless()
api.deferrals.raise_exceptions() # <- this raises the exception

# combo mode:
with api.deferrals.defer_exceptions():
  do_a_thing_that_raises_an_exception()
do_another_thing_that_should_happen_regardless()
api.deferrals.raise_exceptions() # <- this raises the exception

# specific exception mode:
with api.deferrals.raise_exceptions_at_end():
  with api.deferrals.defer_exceptions(exception_types=[StepFailure]):
    raise StepFailure('error') # <- deferred
  with api.deferrals.defer_exceptions(exception_types=[StepFailure]):
    raise InfraFailure('error') # <- not deferred and raises immediately.
"""

import contextlib

from recipe_engine.recipe_api import InfraFailure
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure


class MultipleFailures(StepFailure):
  """An extension of StepFailure that summarizes multiple errors."""

  def __init__(self, errors):
    super().__init__('\n'.join([str(x) for x in errors]))


class MultipleFailuresIncludingInfraFailures(InfraFailure):
  """An extension of InfraFailure that summarizes multiple errors.

  Should include at least one InfraFailure."""

  def __init__(self, errors):
    super().__init__('\n'.join([str(x) for x in errors]))


class DeferralsApi(RecipeApi):
  """A module for deferring actions, such as raising Exceptions."""

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._deferred_exceptions = []

  @contextlib.contextmanager
  def defer_exceptions(self, exception_types=None):
    """Catches exceptions and defers them until raised (see usage above).

    Should be used either in conjunction with deferrals.raise_exceptions_at_end
    or deferrals.raise_exceptions or this will essentially just swallow
    exceptions (and if that's your intent, we prefer
    `api.failures.ignore_exceptions`).

    Note: this can only catch a single exception, so if the intent is for
    exceptions to be swallowed by a long block of code, be aware that every
    step that can throw should be wrapped.

    For more on this see `examples/defer_exceptions_block_incorrect.py`.

    Args:
      exception_types (Optional[List[Type]]): types of exceptions to defer
        (allowing all others through).
    """
    try:
      yield
    except Exception as e:  # pylint: disable=broad-except
      if not exception_types or any(isinstance(e, x) for x in exception_types):
        step = self.m.step('deferring exception until later', cmd=None)
        step.presentation.logs['caught exception'] = repr(e)
        self._deferred_exceptions.append(e)
      else:
        raise e

  def defer_exception(self, exception):
    """Takes an exception and defers it until raised (see usage above).

    Should be used either in conjunction with deferrals.raise_exceptions_at_end
    or deferrals.raise_exceptions or this will essentially just swallow
    exceptions (and if that's your intent, we prefer
    `api.failures.ignore_exceptions`).

    Args:
      exception (Exception): the exception to raise later.
    """
    step = self.m.step('deferring exception until later', cmd=None)
    step.presentation.logs['caught exception'] = repr(exception)
    self._deferred_exceptions.append(exception)

  @contextlib.contextmanager
  def raise_exceptions_at_end(self, prefer_first_type: bool = False):
    """Sets up a context manager to raise deferred failures at the end.

    Note: while using this context manager, if an exception is thrown that is
    *not* caught by the defer_exceptions call above, that exception will take
    precendence over the deferred one. However, the deferred one will still be
    logged.
    """
    caught = False
    try:
      yield
    except Exception as e:
      # Make sure that if an exception that is not caught by `defer_exceptions`
      # is thrown, we surface that exception and not the deferred one.
      caught = True
      raise e
    finally:
      if not caught:
        self.raise_exceptions(prefer_first_type)

  def are_exceptions_pending(self) -> bool:
    """Returns whether any exceptions would be raised by `raise_exceptions`."""
    return bool(self._deferred_exceptions)

  def raise_exceptions(self, prefer_first_type: bool = False):
    """Explicitly raise any deferred exceptions.

    This is the non-context manager approach to using this module. Simply call
    this method at the point where you want deferred exceptions to be raised.

    If multiple exceptions were deferred, the superclass of the raised
    exception depends on the value of `prefer_first_type` and the order in
    which exceptions that were raised:
    - An InfraFailure will be raised if:
      - prefer_first_type is False and _any_ deferred exception was an
        InfraFailure, or
      - prefer_first_type is True and _the first_ deferred exception was an
        InfraFailure.
    - Otherwise, a StepFailure will be raised.
    """
    if self.are_exceptions_pending():
      deferred = self._deferred_exceptions
      self._deferred_exceptions = []
      if len(deferred) == 1:
        raise deferred[0]

      if prefer_first_type:
        raise_infra_failure = isinstance(deferred[0], InfraFailure)
      else:
        raise_infra_failure = any(isinstance(x, InfraFailure) for x in deferred)

      if raise_infra_failure:
        raise MultipleFailuresIncludingInfraFailures(deferred)
      raise MultipleFailures(deferred)
