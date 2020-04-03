# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for logging step output to Google Storage."""

from recipe_engine import recipe_api

import contextlib


class GSStepLoggingApi(recipe_api.RecipeApi):
  """A module for logging step output to Google Storage."""

  def _write_text_to_gs(self, text, gs_path):
    """Writes text to a temp file and then copies to gs_path."""
    with self.m.step.nest('write to {}'.format(gs_path)):
      tempfile = self.m.path.mkstemp()
      self.m.file.write_text('write to temp file', tempfile, text)
      # Put the destination in quotes in case it has spaces.
      self.m.gsutil(['cp', tempfile, "'{}'".format(gs_path)])

  @contextlib.contextmanager
  def log_step_to_gs(self, gs_prefix):
    """Returns a context that logs stdout of the final step to GS.

    Note that only the final step is logged (i.e. the step.active_result
    as the context exits).

    Args:
      gs_prefix (step): Prefix for the logged GS objects. Should contain
        the bucket name, but not the 'gs://' prefix. For example,
        '<bucket>/logging'. If None, nothing is logged.
    """
    try:
      yield
    finally:
      step = self.m.step.active_result
      if gs_prefix and step.stdout:
        gs_path = 'gs://{prefix}/{id}/{step_name}/stdout'.format(
            prefix=gs_prefix,
            id=self.m.buildbucket.build.id,
            step_name=step.name_tokens[-1],
        )
        # Write the link before the write to GS is actually done. This is
        # required because links can't be updated after another step has
        # been run.
        step.presentation.links[
            'stdout (GS mirror)'] = self.m.urls.get_gs_path_url(gs_path)
        self._write_text_to_gs(step.stdout, gs_path)
