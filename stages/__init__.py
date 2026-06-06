# stages/ — Pipeline stage implementations.
#
# Each file implements exactly one stage of the pipeline.
# Only extraction.py and description_parser.py call an LLM.
# All other stages are pure deterministic Python.
