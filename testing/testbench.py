import client as c
import os
import time
import random

from state import State
from multiprocessing import Pool, TimeoutError
from options import Options
from kubernetes.client.rest import ApiException
from pandas import DataFrame


results = {}
label_to_index = {}


class Metric:
    def __init__(self, fn, labels):
        self.fn = fn
        self.labels = labels


class TestBench:
    def __init__(self, metrics, options):
        global results
        # Setup state
        for metric in metrics:
            for label in metric.labels:
                label_to_index[label] = len(label_to_index.keys())

        with Pool() as pool:
            first_write = True
            last_save = time.time()

            for i in range(options.iterations):
                results[i] = [None for _ in range(len(label_to_index.keys()))]
                for metric in metrics:
                    pool.apply_async(metric.fn, args=[i], callback=log_dict)
                time.sleep(options.pulse + random.uniform(0, options.jitter))
                if time.time() - last_save > options.save_every:
                    print("saving...")
                    pool.close()
                    pool.join()

                    save(results, first_write)
                    results = {}
                    last_save = time.time()
                    print("saved...")
                    pool = Pool()
                    first_write = False
            pool.close()
            pool.join()
            save(results, first_write)


def log_dict(result):
    global results
    row_key = result.get("row_key", None)
    if row_key is None:
        return
    del result["row_key"]
    for key in result.keys():
        col_index = label_to_index[key]
        results[row_key][col_index] = result[key]


def test_k8s_cluster_list(row_index):
    return {"row_key": row_index, "k8s_cluster_list_time": client.timed_list_k8s_clusters_no_resp()}


def test_rancher_cluster_list(row_index):
    return {"row_key": row_index, "rancher_cluster_list_time": client.timed_list_rancher_clusters()}


def test_rancher_project_list(row_index):
    return {"row_key": row_index, "rancher_project_list_time": client.timed_list_rancher_projects_no_resp()}


def test_k8s_project_list(row_index):
    return {"row_key": row_index, "k8s_project_list_time": client.timed_list_k8s_projects_no_resp()}


def test_rancher_crud(row_index):
    data = {"row_key": row_index}
    try:
        a = client.timed_crud_rancher_cluster()
        data.update(a)
        data.update(client.timed_crud_rancher_cluster())
    except ApiException as e:
        print("ERROR", e)
    return data


def save(progress, write_columns):
    header = write_columns

    current = DataFrame.from_dict(progress, orient="index", columns=label_to_index.keys())
    current.to_csv(path_or_buf="scale_test.csv", mode="a", header=header)


metrics = [
    Metric(test_rancher_cluster_list, ["rancher_cluster_list_time"]),
    Metric(test_rancher_project_list, ["rancher_project_list_time"]),
    Metric(test_k8s_cluster_list, ["k8s_cluster_list_time"]),
    Metric(test_k8s_project_list, ["k8s_project_list_time"]),
    Metric(test_rancher_crud, ["rancher_create_time", "rancher_get_time",
                               "rancher_update_time", "rancher_delete_time"])
]

token = os.getenv("RANCHER_SCALING_TOKEN")
url = os.getenv("RANCHER_SCALING_URL")
a = c.Auth(token, url=url)
client = c.Client(a)

opts = Options()
TestBench(metrics, opts)
