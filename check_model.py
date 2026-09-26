import pickle

with open(r"C:\projects\UrbanOS\ml\traffic\models\production\traffic_xgboost_model.pkl", 'rb') as f:
    data = pickle.load(f)
    print("Model type:", data.get('model_type'))
    print("Keys:", data.keys())
    if 'model' in data:
        model = data['model']
        print("Model class:", type(model))
        if hasattr(model, 'feature_names_in_'):
            print("Feature names:", model.feature_names_in_)