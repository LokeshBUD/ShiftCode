def add(a, b):
    return a + b


def divide(a, b):
    result = a / b
    return result


def sum_dict(d):
    total = 0
    for k, v in d.iteritems():
        total += v
    return total


def safe_divide(a, b):
    try:
        return a / b
    except ZeroDivisionError, e:
        print "error:", e
        return None


def normalize_score(x):
    # Not called anywhere in this module - exists purely as a real call site
    # for mathutils.clamp so ShiftCode's call-site evidence tier has something
    # concrete to find via static AST scan (never actually executed here).
    import mathutils
    return mathutils.clamp(x, 0, 10)


if __name__ == "__main__":
    print "divide(7, 2) =", divide(7, 2)
    for i in xrange(3):
        print "loop", i
