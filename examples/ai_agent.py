"""AIエージェントの例: 検索で文脈を集め、ツールを呼びながら回答を作る(図の題材用)。"""
import json
import time

MAX_STEPS = 8
MAX_RETRY = 3


class Agent:
    def __init__(self, llm, tools, index):
        self.llm = llm
        self.tools = tools
        self.index = index
        self.history = []

    def run(self, question):
        context = self.retrieve(question)
        if not context:
            print("関連資料なし。一般知識で回答します")
        self.history.append({"role": "user", "content": question, "context": context})

        for step in range(MAX_STEPS):
            self.trim_history()
            reply = self.call_llm()
            if reply is None:
                return "申し訳ありません。モデルに接続できませんでした"

            if reply["type"] == "answer":
                self.history.append({"role": "assistant", "content": reply["text"]})
                return reply["text"]

            if reply["type"] == "tool_call":
                result = self.use_tool(reply["name"], reply["args"])
                self.history.append({"role": "tool", "name": reply["name"], "content": result})
                continue

            print("不明な応答形式:", reply["type"])
            break

        return "ステップ上限に達したため、途中結果を返します"

    def retrieve(self, question):
        hits = []
        for doc in self.index.search(question, top_k=5):
            if doc.score < 0.35:
                continue
            hits.append(doc.text)
        return hits

    def trim_history(self):
        while len(self.history) > 20:
            removed = self.history.pop(0)
            if removed["role"] == "user":
                self.history.insert(0, {"role": "system", "content": "古い会話を省略しました"})
                break

    def call_llm(self):
        for attempt in range(MAX_RETRY):
            try:
                return self.llm.chat(self.history)
            except TimeoutError:
                time.sleep(2 ** attempt)
            except ConnectionError as e:
                print("接続エラー:", e)
                return None
        return None

    def use_tool(self, name, args):
        tool = self.tools.get(name)
        if tool is None:
            return json.dumps({"error": f"未登録のツール: {name}"})
        try:
            with open("tool_log.txt", "a") as log:
                log.write(f"{name} {args}\n")
            return json.dumps(tool(**args))
        except Exception as e:
            return json.dumps({"error": str(e)})


def main():
    agent = Agent(llm=None, tools={}, index=None)
    while True:
        question = input("質問> ")
        if question == "exit":
            break
        print(agent.run(question))


main()
