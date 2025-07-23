#!/bin/bash
cd /home/kavia/workspace/code-generation/railway-ticket-booking-mobile-application-a025c0bb/Backend_Service
source venv/bin/activate
flake8 .
LINT_EXIT_CODE=$?
if [ $LINT_EXIT_CODE -ne 0 ]; then
  exit 1
fi

