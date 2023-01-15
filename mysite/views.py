from django.http import HttpResponse
from django.shortcuts import render
import markdown
import json


def parse_json_tasks(path: str) -> map:
    content = path

    tasks = {}
    try:
        tasks = json.loads(content)
    except:
        raise Exception("wrong format of json, check again")
    return tasks


def build_depedency_map(tasks: map) -> map:
    print(tasks)
    dep_map = {}
    for task in tasks:
        dep_map[task["task_name"]] = task["dependencies"]
    return dep_map


def judge_if_legal(dep_map: map) -> str:
    for task in dep_map:
        for dep in dep_map[task]:
            if dep not in dep_map:
                return dep
    return ""


# 判断拓扑排序是否结束
def is_over(dep_map: map, deleted: list) -> int:
    count = 0
    ret = []
    has_non_zero = False
    for each in dep_map:
        if len(dep_map[each]) != 0:
            has_non_zero = True
        else:
            ret.append(each)
    # 如果存在还有依赖的文件，且依赖为0的文件已经都出列过了，说明有循环依赖
    if (has_non_zero and set(deleted) == set(ret)):
        return 1
    # 所有文件都没有依赖了，说明流程正常走完，没有循环依赖
    if not has_non_zero:
        return 2
    # 说明还有文件可以继续进行依赖剥除，继续操作
    return 0


def judge_circular_reference(dep_map: map) -> int:
    deleted = []
    while True:
        for each in dep_map:
            # 如果某个文件没有依赖，出列，并且所有依赖它的文件，依赖-1
            if len(dep_map[each]) == 0 and each not in deleted:
                for e in dep_map:
                    if each in dep_map[e]:
                        dep_map[e].remove(each)
                deleted.append(each)
                break
        res = is_over(dep_map, deleted)
        if res != 0:
            return res == 1


def revert(origin, curr, changed):
    for i in range(0, len(origin)):
        if origin[i] != curr[i]:
            for j in range(len(curr)-1, 0, -1):
                if curr[j] == origin[i]:
                    curr[j], curr[i] = curr[i], curr[j]
                    changed[j], changed[i] = changed[i], changed[j]
                    break
    return changed


class OP:
    def __init__(self, name, desc, inputs, output, use_global_input, use_global_output):
        self.name = name
        self.desc = desc
        self.inputs = inputs
        self.output = output
        self.use_global_input = use_global_input
        self.use_global_output = use_global_output

    def __str__(self) -> str:
        template = '- {}: {}。 输入参数:{}, 输出参数:{}'
        return template.format(self.name, self.desc, str(self.inputs), self.output)

    def to_code(self):
        template = ''' 
BEGIN_OP({}) {{
{}  RETURN_VAL(your_value);
}}
END_OP
        '''
        input_content = ""
        if self.use_global_input:
            input_content += "  GET_GLOBAL_INPUT(input_type, input_val);\n"
        if len(self.inputs) > 0:
            if "vector" in self.inputs[0]:
                input_type = self.inputs[0][7:-1]
                input_content += "  GET_INPUT_TO_VEC({}, input_list);\n".format(
                    input_type)
            else:
                for index, each in enumerate(self.inputs):
                    input_content += "  GET_INPUT({}, {}, input_{});\n".format(
                        index, each, index)
        input_content += "  //write your code here.\n\n"
        if self.use_global_output:
            input_content += "  WRITE_TO_FINAL_OUTPUT(output_type, output_val);\n"
        res = template.format(self.name, input_content)
        return res


fetch_input_op = OP("FetchInput", "获取全局外部输入", [], ["int"], True, False)
write_output_op = OP("WriteOutput", "将数据输出到全局输出",
                     ["int"], ["int"], False, True)
add_num_op = OP(
    "AddNum", "对输入加上某个数字之后输出。其中数字需要在config里面定义(eg. num=10)", ["int"], ["int"], False, False)
mult_num_op = OP(
    "MultNum", "对输入乘上某个数字之后输出。其中数字需要在config里面定义(eg. num=10)", ["int"], ["int"], False, False)
accum_mult_op = OP(
    "AccumMult", "上游算子的结果进行累计相乘之后输出", ["vector(int)"], ["int"], False, False)
accum_add_op = OP(
    "AccumAdd", "上游算子的结果进行累计相加之后输出", ["vector(int)"], ["int"], False, False)
add_op = OP(
    "Add", "将上游两个算子的数据相加之后输出", ["int", "int"], ["int"], False, False)
mult_op = OP(
    "Mult", "将上游两个算子的数据相乘之后输出", ["int", "int"], ["int"], False, False)

parse_op = OP("ParseRequest", "解析推荐请求", [], ['string'], True, False)

black_op = OP("Blacklist", "获取用户已读结果", ['string'], ['Blacklist'], False, False)

uu_op = OP("UU", "获取用户画像", ['string'], ['UserInfo'], False, False)

recall_op = OP("RecallOp", "召回基础算子", [
               'Blacklist', 'UserInfo'], ['RecallResult'], False, False)

recall_merge_op = OP("RecallMerge", "融合召回结果", ['vector(RecallResult)'], [
                     'RecallResult'], False, False)

basic_rank_op = OP("BasicRank", "粗排算子", ['RecallResult'], [
                   'RankResult'], False, False)

rank_op = OP("Rank", "精排算子", ['RankResult'], ['RankResult'], False, False)

policy_op = OP("Policy", "混排算子", ['RankResult'], [
               'PolicyResult'], False, False)

fill_op = OP("FillResponse", "产出推荐结果", ['PolicyResult'], ['int'], False, True)


default_ops = [fetch_input_op, write_output_op, add_num_op,
               mult_num_op, accum_add_op, accum_mult_op, add_op, mult_op, parse_op, black_op, uu_op, recall_op, recall_merge_op, basic_rank_op, rank_op, policy_op, fill_op]
op_map = {}
task_map = {}
curr_task_map = {}

dep_map = {}


def generate_op_markdown(op_list):
    content = ""
    for op in op_list:
        if len(content) > 0:
            content += "\n" + str(op)
        else:
            content += str(op)
    return markdown.markdown(content, extensions=[
        # 包含 缩写、表格等常用扩展
        'markdown.extensions.extra',
        # 语法高亮扩展
        'markdown.extensions.codehilite',
    ])


def generate_code(tasks: map) -> str:
    task_map = {}
    for each in tasks["tasks"]:
        task_map[each["task_name"]] = each
    template = """
graph LR
   {}
"""
    body = ""
    if len(tasks["tasks"]) == 0:
        return template.format("a((NO_TASK))")
    template2 = "{}(({})) --> {}(({}))\n"
    template1 = "{}(({}))\n"
    for each in tasks["tasks"]:
        if each["async"]:
            body += "style {} stroke-width:2px,stroke-dasharray: 5, 5\n".format(
                each["task_name"])
        if len(each["dependencies"]) > 0:
            for dep in each["dependencies"]:
                body += template2.format(dep, dep+":"+task_map[dep]["op_name"],
                                         each["task_name"], each["task_name"]+":"+each["op_name"])
        else:
            body += template1.format(each["task_name"],
                                     each["task_name"]+":"+each["op_name"])
    return template.format(body)


def generate_input(op_list, op_name):
    for op in op_list:
        if op.name == op_name:
            return op.inputs
    return []


def generate_output(op_list, op_name):
    for op in op_list:
        if op.name == op_name:
            return op.output
    return []


def check_input(inputs, output):
    if len(inputs) == 0:
        if len(output) != 0:
            return "输入参数个数为0，但是输出参数不为0"
        else:
            return ""
    else:
        if "vector" in inputs[0]:
            if len(output) == 0:
                return "缺少输出参数"
            for each in output:
                if inputs[0][7:-1] != each:
                    return "数组参数中每一个输入端类型应该保持一致"
            return ""
        else:
            if len(inputs) > len(output):
                return "输入输出不匹配"
            else:
                if inputs != output[:len(inputs)]:
                    return "输入输出不匹配"
                else:
                    return ""


def task(request):
    user_ip = request.META.get("REMOTE_ADDR")
    if user_ip in task_map:
        tasks = task_map[user_ip]
    else:
        tasks = {"tasks": []}
    if user_ip in curr_task_map:
        curr_task = curr_task_map[user_ip]
    else:
        curr_task = []
    context = {}
    context["curr_tasks"] = curr_task
    op_list = []
    op_list.extend(default_ops)
    if user_ip in op_map:
        op_list.extend(op_map[user_ip])
    context["ops_intro"] = generate_op_markdown(op_list)
    context["ops"] = op_list
    task_name = request.POST.get("task_name")
    err = ""
    if task_name and len(task_name) > 0:
        op_name = request.POST.get("op")
        task = {}
        task["task_name"] = task_name
        task["op_name"] = op_name
        i_deps = []
        if len(request.POST.get("deps").strip()) > 0:
            i_deps = request.POST.get("deps").split(",")
        task["dependencies"] = i_deps
        inputs = generate_input(op_list, op_name)
        d_outputs = []
        for dep in task["dependencies"]:
            for t in tasks["tasks"]:
                if dep == t["task_name"]:
                    if t["async"]:
                        err = "错误:异步算子{}不能被依赖.".format(t["task_name"])
                    op = t["op_name"]
                    d_outputs.extend(generate_output(op_list, op))
                    break
        derr = check_input(inputs, d_outputs)
        err = err+derr
        if len(err) > 0:
            err = "错误:算子{}:{}，算子需要:{}, 实际得到:{}".format(
                op_name, err, inputs, d_outputs)
            context["error"] = err
        else:
            if "tasks" not in tasks:
                tasks["tasks"] = []
            task["config"] = request.POST.get("config")
            exist = False
            for each in tasks["tasks"]:
                if each["task_name"] == task_name:
                    tasks["tasks"].remove(each)
                    old = each
                    exist = True
                    break
            tmp_task = []
            tmp_task.extend(tasks["tasks"].copy())
            tmp_task.append(task)
            tmp_json = json.dumps(tmp_task)
            tmp_tasks = parse_json_tasks(tmp_json)
            dep_map = build_depedency_map(tmp_tasks)
            # 检查是否有非法依赖
            legal = judge_if_legal(dep_map)
            if len(legal) > 0:
                context["error"] = "存在非法依赖{}，检查一下".format(legal)
                if exist:
                    tasks["tasks"].append(old)
            elif judge_circular_reference(dep_map):
                context["error"] = "存在循环依赖"
                if exist:
                    tasks["tasks"].append(old)
            else:
                is_async = False
                is_async = request.POST.get("async")
                if is_async == "yes":
                    is_async = True
                else:
                    is_async = False
                task["async"] = is_async
                if task_name not in curr_task:
                    curr_task.append(task_name)
                tasks["tasks"].append(task)

    context["json"] = json.dumps(tasks)
    print(tasks)
    if "tasks" in tasks:
        context['graph'] = generate_code(tasks)
    else:
        context['graph'] = """graph LR
   a((NO_TASK))
"""
    task_map[user_ip] = tasks
    curr_task_map[user_ip] = curr_task
    return render(request, 'hello.html', context)


def clear(request):
    user_ip = request.META.get("REMOTE_ADDR")
    if user_ip in task_map:
        task_map[user_ip].clear()
    if user_ip in curr_task_map:
        curr_task_map[user_ip].clear()
    ops = []
    if user_ip in op_map:
        ops = op_map[user_ip]
    context = {}
    context["ops_intro"] = generate_op_markdown(default_ops+ops)
    context['graph'] = """graph LR
   a((NO_TASK))
"""
    op = []
    if user_ip in op_map:
        op = op_map[user_ip]
    context["ops"] = default_ops+op
    return render(request, 'hello.html', context)


def ops(request):
    user_ip = request.META.get("REMOTE_ADDR")
    ops = []
    context = {}
    if user_ip in op_map:
        ops = op_map[user_ip]

    if (request.method == 'POST'):
        op_name = request.POST.get("op_name")
        op_desc = request.POST.get("op_desc")
        op_input = request.POST.get("op_input")
        op_output = request.POST.get("op_output")
        op_input_list = [each.strip() for each in op_input.strip().split(",")]
        if len(op_input_list) == 1 and len(op_input_list[0]) == 0:
            op_input_list = []
        op_output_list = [each.strip()
                          for each in op_output.strip().split(",")]
        for each in ops:
            if each.name == op_name:
                ops.remove(each)
        use_op = False
        op_use_input = request.POST.get("global_input")
        if op_use_input == "yes":
            use_op = True
        use_output = False
        op_use_output = request.POST.get("global_output")
        if op_use_output == "yes":
            use_output = True
        op = OP(op_name, op_desc, op_input_list,
                op_output_list, use_op, use_output)
        ops.append(op)
        js = ""
        for each in ops:
            js += each.to_code() + "\n\n"
        context["json"] = js
    op_map[user_ip] = ops
    context["ops"] = ops+default_ops
    return render(request, 'op.html', context)


def clear_op(request):
    user_ip = request.META.get("REMOTE_ADDR")
    if user_ip in op_map:
        op_map[user_ip].clear()
    context = {}
    context["ops"] = default_ops
    return render(request, 'op.html', context)
