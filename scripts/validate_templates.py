"""Compile every Flask/Jinja template and report syntax errors precisely."""
import sys
from pathlib import Path

from jinja2 import DictLoader, Environment, TemplateSyntaxError


def validate_environment(environment):
    failures = []
    for template_name in sorted(environment.list_templates()):
        try:
            environment.get_template(template_name)
        except TemplateSyntaxError as error:
            failures.append((error.name or template_name, error.lineno, str(error)))
    return failures


def report_failures(failures):
    for template_name, line, message in failures:
        print(f"Template validation failed:\nTemplate: {template_name}\nLine: {line}\nError: {message}")


def self_test():
    environment = Environment(loader=DictLoader({'broken.html': '{# unfinished'}))
    failures = validate_environment(environment)
    if len(failures) != 1 or failures[0][0] != 'broken.html' or failures[0][1] != 1:
        report_failures(failures)
        print('Template validator self-test failed.', file=sys.stderr)
        return 1
    if 'Missing end of comment tag' not in failures[0][2]:
        report_failures(failures)
        print('Template validator self-test reported an unexpected error.', file=sys.stderr)
        return 1
    print('Template validator self-test passed (filename, line, and syntax error reported).')
    return 0


def main():
    if '--self-test' in sys.argv[1:]:
        return self_test()

    project_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_dir))
    import app as application

    environment = application.app.jinja_env
    names = sorted(environment.list_templates())
    failures = validate_environment(environment)
    if failures:
        report_failures(failures)
        return 1
    print(f'Validated {len(names)} Jinja templates successfully.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
