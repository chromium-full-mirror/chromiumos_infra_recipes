# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

# infra/proto/src/chromiumos/builder_report.proto
# from PB.chromiumos.build_report import BuildReportBeta as BuildReport


class BuildReportingTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for writing tests with the BuildReporting module."""
