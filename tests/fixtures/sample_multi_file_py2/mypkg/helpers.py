def normalize(items):
    result = {}
    for k, v in items.iteritems():
        result[k] = v * 2
    return result
