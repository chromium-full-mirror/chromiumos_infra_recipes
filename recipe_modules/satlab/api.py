# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re
from urllib import request, parse

from google.protobuf import json_format

from recipe_engine import recipe_api


class Satlab(recipe_api.RecipeApi):
  """Module for Satlab related functionality"""

  def __init__(self, **kwargs):
    super().__init__(**kwargs)

  def stage_build(self, build, target_bucket):
    """Stage a build to a partner bucket. Will raise an exception on failure.

    Args:
      build: string, formated as <board>-release/RXXX-YYY.ZZ.A
      bucket: string, name of gs bucket to stage builds too
    """
    board, milestone, release = self._parse_chromeos_build(build)
    tkn = self._get_oauth_token()

    # Write to file to avoid exposing sensitive token.
    self.m.file.write_text("write headers", "/tmp/headers.txt",
                           f"Authorization: Bearer {tkn}", include_log=False)

    url = f"https://chromeosmoblab.googleapis.com/v1beta1/buildTargets/{board}/models/foo/builds/{release}/artifacts/{target_bucket}:stage?filter=type=release"
    cmd = [
        "curl", "--fail-with-body", "-X", "POST", "-H", "@/tmp/headers.txt", url
    ]

    self.m.step("stage build request", cmd)

  def _get_oauth_token(self):
    """Fetch OAuth token for service account running the task, with a Moblab API scope.
    """
    account = self.m.service_account.default()
    return account.get_access_token(
        ["https://www.googleapis.com/auth/moblabapi"])

  def _parse_chromeos_build(self, build):
    """Pulls out the board, chrome branch, and chromeos version from the fully qualified ChromeOS Build.

    Format is expected to be like <board>-release/RXXX-YYY.ZZZ.AAA.
    """
    m = re.match('(?P<board>.*)-release\/(?P<version>.*)', build)

    if not m:
      raise ValueError("build not formatted correctly")

    v = self.m.cros_version.Version.from_string(m.group('version'))

    return m.group('board'), v.chrome_branch, f'{v.build}.{v.branch}.{v.patch}'
